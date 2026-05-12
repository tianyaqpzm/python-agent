"""
Agent 图工厂

职责：
- 构建全局路由图（Global Router Graph）
- 注入 LangGraph Checkpoint 连接池
- 返回可执行的编译图

架构变更记录：
- v1: 单体 workflow（chat_graph.py）  workflow.compile(checkpointer=checkpointe
- v2: 路由架构（router graph + 3 subgraphs），见 app/agent/router/
"""
from __future__ import annotations

import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.agent.router.graph import build_router_graph

logger = logging.getLogger(__name__)


async def get_graph_runnable(pool):
    """
    获取编译后的路由图（带 Checkpoint 持久化）。

    Args:
        pool: AsyncConnectionPool（由 lifespan 创建的 psycopg 连接池）

    Returns:
        编译后的 CompiledGraph，可直接 ainvoke / astream_events
    """
    checkpointer = AsyncPostgresSaver(pool)
    router_graph = build_router_graph()
    compiled = router_graph.compile(checkpointer=checkpointer)
    logger.info("✅ Router Graph compiled with checkpointer.")
    return compiled
