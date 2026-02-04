import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings
from app.core.nacos import nacos_manager
from app.core.database import engine, init_db
from app.core.mcp_initialization import setup_mcp_clients, connect_clients

logger = logging.getLogger(__name__)

# 定义一个全局集合，用来存放后台任务的引用，防止被 GC
background_tasks = set()


# 🔥 配置函数：禁用 Prepared Statements (解决 consuming input failed)
async def configure_conn(conn):
    conn.prepare_threshold = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    logger.info("Agent starting up...")

    # 1. 初始化业务数据库 (SQLAlchemy)
    try:
        logger.info("⚡ Initializing database tables...")
        await init_db()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        # 建议抛出异常，数据库连不上服务启动也没意义
        raise e

    # 2. 🔥 初始化 LangGraph 专用连接池 (Psycopg)
    # 清洗 URI，确保它是标准的 postgresql:// 格式
    pg_uri = str(settings.DB_URI).replace("+asyncpg", "").replace("+psycopg", "")

    app.state.lg_pool = AsyncConnectionPool(
        conninfo=pg_uri,
        max_size=20,
        min_size=1,  # 保持最小连接数
        # ✅ 关键配置 A: 借出时检查连接健康度
        check=AsyncConnectionPool.check_connection,
        # ✅ 关键配置 B: 禁用预编译语句
        configure=configure_conn,
        # ✅ 关键配置 C: 强制连接 10分钟轮转
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

    # 3. 运行 Setup (确保表结构存在)
    try:
        async with app.state.lg_pool.connection() as conn:
            # 显式开启 autocommit (虽然 pool 已经设了，但保险起见)
            await conn.set_autocommit(True)
            logger.info("⚙️ Running LangGraph table setup...")
            checkpointer = AsyncPostgresSaver(conn)
            await checkpointer.setup()
            logger.info("✅ LangGraph tables setup complete.")
    except Exception as e:
        logger.warning(f"⚠️ LangGraph setup warning: {e}")

    # 4. 🔥 Nacos 连接与注册 (异步非阻塞重试)
    max_retries = 3
    for i in range(max_retries):
        try:
            # 注意：如果 nacos_manager.connect 是同步阻塞的，
            # 在高并发下建议放到 run_in_executor，但在启动阶段勉强可以接受
            nacos_manager.connect()
            nacos_manager.register_service()
            logger.info("✅ Nacos connected and service registered.")
            break
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(
                    f"⚠️ Nacos connection failed, retrying in 2s ({i + 1}/{max_retries})..."
                )
                # ✅✅✅ 必须使用 await asyncio.sleep，不能用 time.sleep
                await asyncio.sleep(2)
            else:
                logger.error("❌ Nacos connection failed after retries.")
                # raise e # 根据需要决定是否终止启动

    # 5. Setup MCP Clients
    try:
        await setup_mcp_clients()
    except Exception as e:
        logger.error(f"❌ MCP Setup failed: {e}")

    # 6. 启动后台任务
    task = asyncio.create_task(connect_clients())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    yield

    # --- Shutdown Logic ---
    logger.info("Agent shutting down...")

    # 7. 资源清理
    try:
        nacos_manager.deregister_service()
    except Exception:
        pass

    # 关闭数据库
    await engine.dispose()  # 关闭 SQLAlchemy
    await app.state.lg_pool.close()  # 关闭 LangGraph Pool
    logger.info("✅ Database resources released.")
