from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Text, DateTime, BigInteger, func
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()

import time

# --- 核心变更：改为动态创建 ---
_engine = None
_AsyncSessionLocal = None
_last_reset_time = 0

def reset_engine():
    """当 Nacos 配置变更时，清空单例以触发重新创建。增加 1 秒防抖。"""
    global _engine, _AsyncSessionLocal, _last_reset_time
    now = time.time()
    if now - _last_reset_time < 1.0:
        return
        
    _engine = None
    _AsyncSessionLocal = None
    _last_reset_time = now
    logger.info("♻️ Database engine and session factory reset.")

def get_engine():
    global _engine
    if _engine is None:
        logger.info(f"🏗️ Creating database engine for {settings.PG_HOST}:{settings.PG_PORT}...")
        _engine = create_async_engine(
            settings.DB_ASYNC_URI,
            echo=False,
            max_overflow=10,
            pool_pre_ping=True,
            pool_size=20,
            pool_recycle=300,  # 缩短至 5 分钟，主动清理可能失效的连接
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
