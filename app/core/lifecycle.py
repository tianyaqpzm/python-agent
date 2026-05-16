import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Set, Any
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings
from app.core.nacos import nacos_manager
from app.core.database import get_engine, init_db, get_lg_pool, close_db_resources
from app.core.mcp_initialization import setup_mcp_clients, connect_clients

logger = logging.getLogger(__name__)

# 定义一个全局集合，用来存放后台任务的引用，防止被 GC
background_tasks: Set[asyncio.Task[Any]] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    logger.info("Agent starting up...")

    # 1. 🔥 最优先：Nacos 连接与配置加载
    try:
        nacos_manager.connect()
        # 启动配置监听并执行首次同步
        from app.core.dynamic_config import dynamic_config
        dynamic_config.watch_config()
        
        # 注册服务
        nacos_manager.register_service()
        logger.info("✅ Nacos initialization and config sync complete.")
    except Exception as e:
        logger.warning(f"⚠️ Nacos initialization failed: {e}. Falling back to local env.")

    # 2. 初始化核心数据库 (SQLAlchemy)
    try:
        await init_db()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise e

    # 3. 🔥 初始化 LangGraph 专用连接池 (现在通过 database.py 统一管理)
    try:
        pool = await get_lg_pool()
        # 运行 LangGraph Setup
        async with pool.connection() as conn:
            await conn.set_autocommit(True)
            logger.info("⚙️ Running LangGraph table setup...")
            checkpointer = AsyncPostgresSaver(conn)
            await checkpointer.setup()
            logger.info("✅ LangGraph tables setup complete.")
    except Exception as e:
        logger.warning(f"⚠️ LangGraph setup warning: {e}")

    # 4. MCP Clients 延迟加载：由 /chat 接口根据用户偏好动态触发
    # 不需要在这里进行 setup_mcp_clients()

    yield

    # --- Shutdown Logic ---
    logger.info("Agent shutting down...")

    # 6. 关闭 MCP 注册中心
    try:
        from app.core.mcp_registry import mcp_tool_registry
        await mcp_tool_registry.teardown()
    except Exception as e:
        logger.warning(f"⚠️ MCPToolRegistry teardown failed: {e}")

    # 7. 资源清理
    try:
        nacos_manager.deregister_service()
    except Exception as e:
        logger.warning(f"⚠️ Nacos deregister failed: {e}")

    # 统一释放数据库资源
    await close_db_resources()
    logger.info("✅ Agent shutdown complete.")
