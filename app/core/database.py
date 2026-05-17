from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Text, DateTime, BigInteger, func
from psycopg_pool import AsyncConnectionPool
from app.core.config import settings
from typing import Any, Dict, List, Optional
import logging
import asyncio
import time

logger = logging.getLogger(__name__)

Base = declarative_base()

import time

# --- 核心变更：改为动态创建 ---
_engine = None
_AsyncSessionLocal = None
_lg_pool = None
_last_reset_time = 0
_pool_lock = asyncio.Lock()

def reset_engine():
    """当 Nacos 配置变更时，清空单例以触发重新创建。增加 1 秒防抖。"""
    global _engine, _AsyncSessionLocal, _lg_pool, _last_reset_time
    now = time.time()
    if now - _last_reset_time < 1.0:
        return
        
    _engine = None
    _AsyncSessionLocal = None
    
    # 注意：这里我们只置空，旧的 pool 会在下次 get_lg_pool 时被替换或在 shutdown 时清理
    # 如果在运行中频繁重置，可能需要更复杂的销毁逻辑
    _lg_pool = None
    
    _last_reset_time = now
    logger.info("♻️ Database engine and session factory reset (including LangGraph pool).")

def get_engine():
    global _engine
    if _engine is None:
        logger.info(f"🏗️ Creating database engine for {settings.PG_HOST}:{settings.PG_PORT}...")
        _engine = create_async_engine(
            settings.DB_ASYNC_URI,
            echo=False,
            pool_pre_ping=True,
            pool_size=30,          # 增加到 30
            max_overflow=20,       # 增加到 20
            pool_timeout=30,       # 显式设置 30s 超时
            pool_recycle=300,      # 缩短至 5 分钟，主动清理可能失效的连接
            connect_args={
                "keepalives": 1,
                "keepalives_idle": 10,
                "keepalives_interval": 5,
                "keepalives_count": 3,
            }
        )
    return _engine

def get_sessionmaker():
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _AsyncSessionLocal

def AsyncSessionLocal():
    """
    向后兼容函数：可以直接像以前一样作为上下文管理器使用
    注意：在 async with 后面加括号：async with AsyncSessionLocal()
    """
    return get_sessionmaker()()

async def configure_conn(conn: Any) -> None:
    """禁用 Prepared Statements (解决 consuming input failed)"""
    conn.prepare_threshold = None

async def get_lg_pool():
    """
    获取 LangGraph 专用的 psycopg 连接池。
    支持动态重连（通过 reset_engine 置空）。
    """
    global _lg_pool
    if _lg_pool is None:
        async with _pool_lock:
            if _lg_pool is None:
                pg_uri = settings.DB_URI.replace("+asyncpg", "").replace("+psycopg", "")
                # 重新构造最新 URI 以防 settings 未及时同步到 DB_URI 属性
                if hasattr(settings, "PG_HOST"):
                    pg_uri = f"postgresql://{settings.PG_USER}:{settings.PG_PASSWORD}@{settings.PG_HOST}:{settings.PG_PORT}/{settings.PG_DB}?sslmode=require&connect_timeout=10"

                logger.info("🏗️ Creating LangGraph connection pool (psycopg_pool)...")
                _lg_pool = AsyncConnectionPool(
                    conninfo=pg_uri,
                    max_size=50,       # 增加到 50，防止高并发下 exhaustion
                    min_size=1,
                    check=AsyncConnectionPool.check_connection,
                    configure=configure_conn,  # 🔥 关键：注入配置回调
                    max_lifetime=600,
                    reconnect_timeout=60.0,
                    kwargs={
                        "autocommit": True,
                        "keepalives": 1,
                        "keepalives_idle": 10,
                        "keepalives_interval": 5,
                        "keepalives_count": 3,
                    },
                )
                await _lg_pool.open()
                logger.info("✅ LangGraph Checkpoint Pool initialized (max_size=50).")
    return _lg_pool

async def close_db_resources():
    """在应用关闭时释放所有数据库资源。"""
    global _engine, _lg_pool
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("✅ SQLAlchemy engine disposed.")
    
    if _lg_pool:
        await _lg_pool.close()
        _lg_pool = None
        logger.info("✅ LangGraph pool closed.")

# --- 模型定义保持不变 ---
class ChatMessageModel(Base):
    __tablename__ = "ms_chat_message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # 'user' or 'ai'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# --- 数据库操作方法 ---
async def get_db():
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session

async def init_db():
    engine = get_engine()
    async with engine.begin() as conn:
        logger.info("🛠️ Running database migrations (create_all)...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables initialized successfully.")
