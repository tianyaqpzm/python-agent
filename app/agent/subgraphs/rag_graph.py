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
from app.core.llm_factory import LLMFactory
from app.core.limiter import LimiterRegistry
from app.services.prompt_service import prompt_service
from app.services.kb.retrieval import RetrievalService

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
    # a. 获取最新 LLM 配置
    provider = dynamic_config.llm_provider
    base_url = dynamic_config.llm_base_url
    model = dynamic_config.llm_model
    api_key = dynamic_config.llm_api_key

    # b. 从 MCPToolRegistry 获取工具（动态，无硬编码）
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)

    # c. 初始化 LLM 并绑定工具
    llm = LLMFactory.get_llm(
        provider=provider, base_url=base_url, model_name=model, api_key=api_key
    )
    if tools:
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
    limiter = await LimiterRegistry.get_limiter(f"chat:{model}", dynamic_config.llm_rpm or 10)
    async with limiter:
        response = await llm.ainvoke(messages)

    res_state: Dict[str, Any] = {"messages": [response]}
    if rag_sources:
        res_state["sources"] = rag_sources
        res_state["rag_sources"] = rag_sources
    else:
        res_state["sources"] = []
        res_state["rag_sources"] = []

    return res_state


def _rag_should_continue(state: RagSubState) -> str:
    """工具调用路由：有 tool_calls 则进入工具节点，否则结束。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
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

    builder.set_entry_point("rag_agent")
    builder.add_conditional_edges("rag_agent", _rag_should_continue)
    builder.add_edge("tools", "rag_agent")

    return builder
