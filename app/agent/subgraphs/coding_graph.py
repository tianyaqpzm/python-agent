"""
Coding 子图实现

负责处理编程相关意图（代码生成、调试、算法实现等）。
支持：
1. 动态 LLM 配置
2. MCP 工具调用
3. 系统人格 Prompt 加载（slug: coding_assistant）
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.agent.state import CodingSubState
from app.core.dynamic_config import dynamic_config
from app.core.limiter import LimiterRegistry
from app.services.prompt_service import prompt_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


async def coding_agent_node(state: CodingSubState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Coding 子图核心节点。
    """
    # b. 从 MCPToolRegistry 获取工具
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)

    # c. 获取 LLM 实例（自动感知配置变更，利用缓存）
    llm = llm_service.get_default_llm()
    if tools:
        llm = llm.bind_tools(tools)

    messages = list(state.get("messages", []))

    # d. 加载人格 Prompt
    auth_header = state.get("auth_header") or config.get("configurable", {}).get("auth_header")
    headers = {"Authorization": auth_header} if auth_header else {}
    
    try:
        system_prompt = await prompt_service.get_rendered_prompt(
            "coding_assistant",
            variables={},
            headers=headers,
            fallback="你是一个高级编程专家。请协助用户编写、调试和优化代码。你可以调用工具来查看文件、运行测试或执行代码。"
        )
        messages = [SystemMessage(content=system_prompt)] + messages
    except Exception as exc:
        logger.error("Failed to load coding_assistant prompt: %s", exc)

    # e. 调用 LLM（带速率限制）
    model_name = dynamic_config.llm_model
    limiter = await LimiterRegistry.get_limiter(f"chat:{model_name}", dynamic_config.llm_rpm or 10)
    from app.agent.callbacks.token_usage import TokenUsageCallbackHandler
    cb = TokenUsageCallbackHandler("CODING")
    
    async with limiter:
        response = await llm.ainvoke(messages, config={"callbacks": [cb]})

    return {"messages": [response]}


async def coding_final_answer_node(state: CodingSubState, config: RunnableConfig) -> Dict[str, Any]:
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


def _coding_should_continue(state: CodingSubState) -> str:
    """判断是否继续执行工具（含迭代次数保护）。"""
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
                "⚠️ Coding subgraph reached max tool iterations (%d), routing to final_answer.",
                MAX_TOOL_ITERATIONS,
            )
            return "final_answer"
        return END

    if is_tool_call:
        return "tools"
    return END


async def _coding_tool_node(state: CodingSubState, config: RunnableConfig) -> Dict[str, Any]:
    """执行工具。"""
    from app.core.mcp_registry import mcp_tool_registry
    tools = mcp_tool_registry.get_langchain_tools(config=config)
    node = ToolNode(tools)
    return await node.ainvoke(state, config)


def build_coding_subgraph() -> StateGraph:
    """
    构建 Coding 子图（未编译）。
    """
    builder = StateGraph(CodingSubState)
    
    builder.add_node("coding_agent", coding_agent_node)
    builder.add_node("tools", _coding_tool_node)
    builder.add_node("final_answer", coding_final_answer_node)

    builder.set_entry_point("coding_agent")
    builder.add_conditional_edges("coding_agent", _coding_should_continue)
    builder.add_edge("tools", "coding_agent")
    builder.add_edge("final_answer", END)

    return builder
