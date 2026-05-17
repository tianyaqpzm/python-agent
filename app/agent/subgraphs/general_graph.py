"""
General 子图实现

通用对话子图，处理不属于 RAG 或 Coding 意图的请求。
支持：
1. 动态 LLM 配置加载
2. MCP 工具调用（通过 MCPToolRegistry）
3. 系统人格 Prompt 加载（slug: general_assistant）
4. 多轮对话状态保留
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.agent.state import GlobalState
from app.core.dynamic_config import dynamic_config
from app.core.limiter import LimiterRegistry
from app.services.prompt_service import prompt_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


async def general_agent_node(state: GlobalState, config: RunnableConfig) -> Dict[str, Any]:
    """
    General 子图核心节点：通用对话生成。
    """
    # b. 从 MCPToolRegistry 获取工具（动态，无硬编码）
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)

    # c. 获取 LLM 实例（自动感知配置变更，利用缓存）
    llm = llm_service.get_default_llm()
    if tools:
        logger.info("🛠️ Binding %d MCP tools to LLM: %s", len(tools), [t.name for t in tools])
        llm = llm.bind_tools(tools)

    messages = list(state.get("messages", []))

    # d. 加载人格 Prompt
    auth_header = state.get("auth_header") or config.get("configurable", {}).get("auth_header")
    headers = {"Authorization": auth_header} if auth_header else {}
    
    try:
        system_prompt = await prompt_service.get_rendered_prompt(
            "general_assistant",
            variables={},
            headers=headers,
            fallback="你是一个全能助手，能够协助用户解决各种问题，并在需要时调用工具。"
        )
        # 将系统消息插入到对话历史最前面
        messages = [SystemMessage(content=system_prompt)] + messages
    except Exception as exc:
        logger.error("Failed to load general_assistant prompt: %s", exc)

    # e. 调用 LLM（带速率限制）
    model_name = dynamic_config.llm_model
    limiter = await LimiterRegistry.get_limiter(f"chat:{model_name}", dynamic_config.llm_rpm or 10)
    async with limiter:
        response = await llm.ainvoke(messages)

    return {"messages": [response]}


async def general_final_answer_node(state: GlobalState, config: RunnableConfig) -> Dict[str, Any]:
    """
    当达到迭代上限时的强制回复节点。
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
MAX_TOOL_ITERATIONS = 2


def _general_should_continue(state: GlobalState) -> str:
    """工具调用路由逻辑（含迭代次数保护）。"""
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
                "⚠️ General subgraph reached max tool iterations (%d), routing to final_answer.",
                MAX_TOOL_ITERATIONS,
            )
            return "final_answer"
        return END

    if is_tool_call:
        return "tools"
    return END


async def _general_tool_node(state: GlobalState, config: RunnableConfig) -> Dict[str, Any]:
    """执行 MCP 工具调用。"""
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)
    node = ToolNode(tools)
    return await node.ainvoke(state, config)


def build_general_subgraph() -> StateGraph:
    """
    构建 General 子图（未编译）。

    工作流：
    general_agent -> (conditional) -> tools -> general_agent
    """
    builder = StateGraph(GlobalState)
    
    builder.add_node("general_agent", general_agent_node)
    builder.add_node("tools", _general_tool_node)
    builder.add_node("final_answer", general_final_answer_node)

    builder.set_entry_point("general_agent")
    builder.add_conditional_edges("general_agent", _general_should_continue)
    builder.add_edge("tools", "general_agent")
    builder.add_edge("final_answer", END)

    return builder
