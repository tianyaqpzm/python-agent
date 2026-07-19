"""
RAG 子图

迁移自 chat_graph.py 的核心逻辑，增强点：
1. 使用 MCPToolRegistry 替代手写 MCP 客户端
2. 状态使用 RagSubState，字段更精确
3. 保持 RAG 检索 + 动态 Prompt + Tool Call 的完整流程
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.agent.state import RagSubState
from app.core.dynamic_config import dynamic_config
from app.core.limiter import LimiterRegistry
from app.services.prompt_service import prompt_service
from app.services.kb.retrieval import RetrievalService
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


async def rag_agent_node(state: RagSubState, config: RunnableConfig) -> Dict[str, Any]:
    """
    RAG 子图的核心节点：检索增强生成。

    执行流程：
    1. 从注册中心获取 MCP 工具（动态加载，无硬编码）
    2. 向量检索知识库上下文
    3. 动态加载人格 Prompt
    4. 调用 LLM（绑定工具）
    """
    # b. 从 MCPToolRegistry 获取工具（动态，无硬编码）
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)

    # c. 获取 LLM 实例（自动感知配置变更，利用缓存）
    llm = llm_service.get_default_llm()
    if tools:
        logger.info("🛠️ Binding %d MCP tools to LLM for RAG: %s", len(tools), [t.name for t in tools])
        llm = llm.bind_tools(tools)

    messages = list(state.get("messages", []))

    # d. RAG 检索增强
    topic_id = state.get("topic_id") or config.get("configurable", {}).get("topic_id")
    auth_header = state.get("auth_header") or config.get("configurable", {}).get("auth_header")
    headers = {"Authorization": auth_header} if auth_header else {}
    rag_sources: list = []

    if topic_id:
        try:
            human_messages = [m for m in messages if isinstance(m, HumanMessage)]
            user_query = ""
            if human_messages:
                last = human_messages[-1]
                if isinstance(last.content, str):
                    user_query = last.content
                elif isinstance(last.content, list):
                    user_query = " ".join(
                        p.get("text", "") for p in last.content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ).strip()

            if user_query:
                ret_svc = RetrievalService()
                context_docs = await ret_svc.search(query=user_query, category=topic_id, top_k=5)
                if context_docs:
                    context_str = "\n---\n".join([d.get("content", "") for d in context_docs])
                    rag_sources = [
                        {
                            "title": d.get("title", "未知文档"),
                            "url": d.get("url", ""),
                            "snippet": d.get("content", "")[:200],
                        }
                        for d in context_docs
                    ]

                    # 动态 Prompt 管理
                    prompt_slug = (
                        "chef_persona_rag" if topic_id == "topic_recipe_001" else "default_kb_assistant"
                    )
                    system_prompt = await prompt_service.get_rendered_prompt(
                        prompt_slug,
                        variables={"context": context_str},
                        headers=headers,
                        fallback=f"你是一个知识库助手。\n\n相关内容：\n{context_str}"
                    )

                    messages = [SystemMessage(content=system_prompt)] + messages
        except Exception as exc:
            logger.error("RAG retrieval failed: %s", exc)

    # e. 调用 LLM（带速率限制）
    model_name = dynamic_config.llm_model
    limiter = await LimiterRegistry.get_limiter(f"chat:{model_name}", dynamic_config.llm_rpm or 10)
    from app.agent.callbacks.token_usage import TokenUsageCallbackHandler
    cb = TokenUsageCallbackHandler("RAG")
    
    async with limiter:
        response = await llm.ainvoke(messages, config={"callbacks": [cb]})

    res_state: Dict[str, Any] = {"messages": [response]}
    if rag_sources:
        res_state["sources"] = rag_sources
        res_state["rag_sources"] = rag_sources
    else:
        res_state["sources"] = []
        res_state["rag_sources"] = []

    return res_state


async def rag_final_answer_node(state: RagSubState, config: RunnableConfig) -> Dict[str, Any]:
    """
    当达到迭代上限时的强制回复节点。
    不再绑定工具，强制 LLM 总结当前信息。
    """
    llm = llm_service.get_default_llm()
    messages = list(state.get("messages", []))

    # 注入强制结束指令
    messages.append(SystemMessage(content="⚠️ 系统提示：已达到工具调用次数上限。请不要再尝试调用任何工具，直接根据目前已有的信息（包括之前工具返回的错误或结果）给用户一个最终的总结性答复。"))

    model_name = dynamic_config.llm_model
    limiter = await LimiterRegistry.get_limiter(f"chat:{model_name}", dynamic_config.llm_rpm or 10)
    async with limiter:
        response = await llm.ainvoke(messages)

    return {"messages": [response]}


# 子图最大工具调用迭代次数（防止 LLM 工具调用失败时无限循环）
MAX_TOOL_ITERATIONS = 5


def _rag_should_continue(state: RagSubState) -> str:
    """工具调用路由（含迭代次数保护）。"""
    messages = state.get("messages", [])
    if not messages:
        return END

    # 统计已执行的工具调用轮次
    tool_call_rounds = sum(
        1 for m in messages if getattr(m, "tool_calls", None)
    )

    last = messages[-1]
    is_tool_call = bool(getattr(last, "tool_calls", None))

    if tool_call_rounds >= MAX_TOOL_ITERATIONS:
        if is_tool_call:
            logger.warning(
                "⚠️ RAG subgraph reached max tool iterations (%d), routing to final_answer.",
                MAX_TOOL_ITERATIONS,
            )
            return "final_answer"
        return END

    if is_tool_call:
        return "tools"
    return END


async def _rag_tool_node(state: RagSubState, config: RunnableConfig) -> Dict[str, Any]:
    """动态工具执行节点，使用 MCPToolRegistry 中的工具。"""
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)
    node = ToolNode(tools)
    return await node.ainvoke(state, config)


def build_rag_subgraph() -> StateGraph:
    """
    构建 RAG 子图（未编译）。

    节点：
    - rag_agent: 检索 + 生成
    - tools: MCP 工具执行

    Returns:
        未编译的 StateGraph
    """
    builder = StateGraph(RagSubState)

    builder.add_node("rag_agent", rag_agent_node)
    builder.add_node("tools", _rag_tool_node)
    builder.add_node("final_answer", rag_final_answer_node)

    builder.set_entry_point("rag_agent")
    builder.add_conditional_edges("rag_agent", _rag_should_continue)
    builder.add_edge("tools", "rag_agent")
    builder.add_edge("final_answer", END)

    return builder
