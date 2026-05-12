import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Set, Any
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings
from app.core.nacos import nacos_manager
from app.core.database import get_engine, init_db
from app.core.mcp_initialization import setup_mcp_clients, connect_clients

logger = logging.getLogger(__name__)

# 定义一个全局集合，用来存放后台任务的引用，防止被 GC
background_tasks: Set[asyncio.Task[Any]] = set()


# 🔥 配置函数：禁用 Prepared Statements (解决 consuming input failed)
async def configure_conn(conn: Any) -> None:
    conn.prepare_threshold = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    logger.info("Agent starting up...")

    # 1. 🔥 最优先：Nacos 连接与配置加载
    # 这样后续的 init_db() 就能用上 Nacos 里配置的 PG_HOST 等信息
    try:
        nacos_manager.connect()
        # 启动配置监听并执行首次同步
        from app.core.dynamic_config import dynamic_config
        dynamic_config.watch_config()
        
        # 注册服务 (可选：也可以放在最后注册，确保服务就绪后再暴露)
        nacos_manager.register_service()
        logger.info("✅ Nacos initialization and config sync complete.")
    except Exception as e:
        logger.warning(f"⚠️ Nacos initialization failed: {e}. Falling back to local env.")

    # 2. 初始化核心数据库 (SQLAlchemy)
    try:
        # 打印关键连接信息辅助定位 (脱敏密码)
        db_info = f"Host=[{settings.PG_HOST}], Port=[{settings.PG_PORT}], User=[{settings.PG_USER}], DB=[{settings.PG_DB}]"
        logger.info(f"⚡ Initializing database tables. Target: {db_info}")
        
        await init_db()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        db_info = f"Host=[{settings.PG_HOST}], Port=[{settings.PG_PORT}], User=[{settings.PG_USER}], DB=[{settings.PG_DB}]"
        logger.error(f"❌ Database initialization failed for {db_info}")
        logger.error(f"   Error Details: {e}")
        # 建议抛出异常，数据库连不上服务启动也没意义
        raise e

    # 3. 🔥 初始化 LangGraph 专用连接池 (Psycopg)
    # 因为 settings 可能被 Nacos 更新了，所以这里重新生成干净的 URI
    pg_uri = str(settings.DB_URI).replace("+asyncpg", "").replace("+psycopg", "")
    # 如果 settings.DB_URI 还是旧的，我们根据最新的 host/port 重新构造 (保险做法)
    if hasattr(settings, "PG_HOST"):
        pg_uri = f"postgresql://{settings.PG_USER}:{settings.PG_PASSWORD}@{settings.PG_HOST}:{settings.PG_PORT}/{settings.PG_DB}"

    app.state.lg_pool = AsyncConnectionPool(
        conninfo=pg_uri,
        max_size=20,
        min_size=1,
        check=AsyncConnectionPool.check_connection,
        configure=configure_conn,
        max_lifetime=600,
        kwargs={
            "autocommit": True,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
    )
    await app.state.lg_pool.open()
    logger.info("✅ LangGraph Checkpoint Pool created.")

    # 4. 运行 LangGraph Setup
    try:
        async with app.state.lg_pool.connection() as conn:
            await conn.set_autocommit(True)
            logger.info("⚙️ Running LangGraph table setup...")
            checkpointer = AsyncPostgresSaver(conn)
            await checkpointer.setup()
            logger.info("✅ LangGraph tables setup complete.")
    except Exception as e:
        logger.warning(f"⚠️ LangGraph setup warning: {e}")

    # 5. Setup MCP Clients
    try:
        await setup_mcp_clients()
    except Exception as e:
        logger.error(f"❌ MCP Setup failed: {e}")

    # 6. 启动后台任务 (例如连接 MCP 客户端)
    task = asyncio.create_task(connect_clients())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    yield

    # --- Shutdown Logic ---
    logger.info("Agent shutting down...")

    # 7. 关闭 MCP 注册中心（官方 SDK 连接清理）
    try:
        from app.core.mcp_registry import mcp_tool_registry
        await mcp_tool_registry.teardown()
    except Exception as e:
        logger.warning(f"⚠️ MCPToolRegistry teardown failed: {e}")

    # 8. 资源清理
    try:
        nacos_manager.deregister_service()
    except Exception as e:
        logger.warning(f"⚠️ Nacos deregister failed: {e}")

    # 关闭数据库
    await get_engine().dispose()  # 关闭 SQLAlchemy
    await app.state.lg_pool.close()  # 关闭 LangGraph Pool
    logger.info("✅ Database resources released.")
