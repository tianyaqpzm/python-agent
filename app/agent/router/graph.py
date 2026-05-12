"""
Global Router Graph

将用户意图路由到对应子图：
  router_node → [rag_subgraph | coding_subgraph | general_subgraph | remote_agent_subgraph]

两种对接模式：
  模式 A（本地子图）：rag / coding / general —— 进程内执行，当前已实现
  模式 B（A2A 远端）：remote_agent —— 委托给外部 Agent，HTTP 调用待实现

子图以 compiled graph 的形式作为节点嵌入，
保证每个子图的状态隔离和可测试性。
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from app.agent.state import GlobalState, IntentType
from app.agent.router.node import router_node

logger = logging.getLogger(__name__)

# 所有合法的路由目标节点名
_RouteTarget = Literal[
    "rag_subgraph",
    "coding_subgraph",
    "general_subgraph",
    "remote_agent_subgraph",
]


def _route_by_intent(state: GlobalState) -> _RouteTarget:
    """
    条件边路由函数：根据 intent 字段选择目标子图节点。

    模式 A（本地）：rag / coding / general → 对应本地子图
    模式 B（远端）：remote_agent → A2A 远端 Agent 子图
    """
    intent: IntentType = state.get("intent") or "general"
    route_map: dict[str, _RouteTarget] = {
        # ── 模式 A：本地子图 ────────────────────────────────────────────────
        "rag":     "rag_subgraph",
        "coding":  "coding_subgraph",
        "general": "general_subgraph",
        # ── 模式 B：A2A 远端 Agent ─────────────────────────────────────────
        "remote_agent": "remote_agent_subgraph",
    }
    target = route_map.get(intent, "general_subgraph")
    logger.info("🔀 Routing intent='%s' → %s", intent, target)
    return target  # type: ignore[return-value]


def build_router_graph() -> StateGraph:
    """
    构建并返回全局路由图（未编译）。

    节点清单：
    ┌─ 路由节点 ───────────────────────────────────────────────────────────────┐
    │  router              意图分类（关键词优先 + LLM fallback）                │
    └──────────────────────────────────────────────────────────────────────────┘
    ┌─ 模式 A：本地子图 ───────────────────────────────────────────────────────┐
    │  rag_subgraph        RAG 检索增强生成 + MCP 工具调用                     │
    │  coding_subgraph     代码生成（Dummy，待扩展）                            │
    │  general_subgraph    通用对话（Dummy，待扩展）                            │
    └──────────────────────────────────────────────────────────────────────────┘
    ┌─ 模式 B：A2A 远端 Agent ────────────────────────────────────────────────┐
    │  remote_agent_subgraph  A2A 委托（结构完整，HTTP 调用待实现）            │
    └──────────────────────────────────────────────────────────────────────────┘

    Returns:
        未编译的 StateGraph，供 factory.py 添加 checkpointer 后编译。
    """
    # ── 延迟导入子图（避免模块循环依赖）──────────────────────────────────────
    from app.agent.subgraphs.rag_graph import build_rag_subgraph
    from app.agent.subgraphs.coding_graph import build_coding_subgraph
    from app.agent.subgraphs.general_graph import build_general_subgraph
    from app.agent.subgraphs.remote_agent_graph import build_remote_agent_subgraph

    # ── 编译子图 ────────────────────────────────────────────────────────────
    rag_graph          = build_rag_subgraph().compile()
    coding_graph       = build_coding_subgraph().compile()
    general_graph      = build_general_subgraph().compile()
    remote_agent_graph = build_remote_agent_subgraph().compile()

    # ── 构建主图 ────────────────────────────────────────────────────────────
    builder = StateGraph(GlobalState)

    # 1. 意图路由节点
    builder.add_node("router", router_node)

    # 2a. 模式 A：本地子图节点
    builder.add_node("rag_subgraph",     rag_graph)
    builder.add_node("coding_subgraph",  coding_graph)
    builder.add_node("general_subgraph", general_graph)

    # 2b. 模式 B：A2A 远端 Agent 节点
    builder.add_node("remote_agent_subgraph", remote_agent_graph)

    # 3. 入口 → 路由节点
    builder.set_entry_point("router")

    # 4. 路由节点 → 条件边 → 各子图
    builder.add_conditional_edges(
        "router",
        _route_by_intent,
        {
            "rag_subgraph":          "rag_subgraph",
            "coding_subgraph":       "coding_subgraph",
            "general_subgraph":      "general_subgraph",
            "remote_agent_subgraph": "remote_agent_subgraph",
        },
    )

    # 5. 所有子图 → END
    builder.add_edge("rag_subgraph",          END)
    builder.add_edge("coding_subgraph",       END)
    builder.add_edge("general_subgraph",      END)
    builder.add_edge("remote_agent_subgraph", END)

    return builder
