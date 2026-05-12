"""
General 子图（Dummy 实现）

通用对话子图，处理不属于 RAG 或 Coding 意图的请求。
后续可接入通用 LLM 对话能力。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END

from app.agent.state import GlobalState

logger = logging.getLogger(__name__)


async def general_agent_node(state: GlobalState, config: RunnableConfig) -> Dict[str, Any]:
    """
    General 子图占位节点。

    TODO: 后续实现通用对话逻辑：
    - 调用通用 LLM
    - 支持多轮对话记忆
    """
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            last_user_msg = m.content if isinstance(m.content, str) else str(m.content)
            break

    logger.info("💬 General SubGraph triggered | query='%s'", last_user_msg[:60])

    placeholder_response = (
        f"[General SubGraph] 您好！我收到了您的问题：{last_user_msg}\n\n"
        "🚧 通用对话子图正在建设中，将很快支持多轮对话。"
    )

    return {
        "messages": [AIMessage(content=placeholder_response)],
        "sources": [],
    }


def build_general_subgraph() -> StateGraph:
    """
    构建 General 子图（未编译）。

    Returns:
        未编译的 StateGraph
    """
    builder = StateGraph(GlobalState)
    builder.add_node("general_agent", general_agent_node)
    builder.set_entry_point("general_agent")
    builder.add_edge("general_agent", END)
    return builder
