from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.services.chat_graph import workflow
import logging

logger = logging.getLogger(__name__)


async def get_graph_runnable(conn):
    """
    业务逻辑 -> 用 asyncpg (SQLAlchemy) -> 高性能。
    LangGraph -> 用 psycopg (官方 Saver) -> 高可靠、零维护。
    Get the compiled graph runnable with checkpointer.
    """
    # Initialize checkpointer with the connection pool
    checkpointer = AsyncPostgresSaver(conn)
    return workflow.compile(checkpointer=checkpointer)
