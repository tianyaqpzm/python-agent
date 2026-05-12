"""
Coding 子图（Dummy 实现）

占位子图，验收阶段验证路由正确性。
后续扩展：集成代码生成 LLM、代码执行沙箱等。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END

from app.agent.state import CodingSubState

logger = logging.getLogger(__name__)


async def coding_agent_node(state: CodingSubState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Coding 子图占位节点。

    TODO: 后续实现代码生成逻辑：
    - 提取用户指定的语言（Python/Java/TS）
    - 调用 Code LLM（如 DeepSeek Coder）
    - 可选：调用代码执行工具验证
    """
    messages = state.get("messages", [])
    last_user_msg = ""
    for m in reversed(messages):
        if hasattr(m, "type") and m.type == "human":
            last_user_msg = m.content if isinstance(m.content, str) else str(m.content)
            break

    logger.info("💻 Coding SubGraph triggered | query='%s'", last_user_msg[:60])

    placeholder_response = (
        f"[Coding SubGraph] 已接收您的编程请求：{last_user_msg}\n\n"
        "🚧 该子图正在建设中，将很快支持代码生成与调试功能。"
    )

    return {
        "messages": [AIMessage(content=placeholder_response)],
        "code_language": "unknown",
        "code_result": placeholder_response,
        "sources": [],
    }


def build_coding_subgraph() -> StateGraph:
    """
    构建 Coding 子图（未编译）。

    Returns:
        未编译的 StateGraph
    """
    builder = StateGraph(CodingSubState)
    builder.add_node("coding_agent", coding_agent_node)
    builder.set_entry_point("coding_agent")
    builder.add_edge("coding_agent", END)
    return builder
