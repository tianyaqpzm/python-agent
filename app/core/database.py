from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Text, DateTime, BigInteger, func
from app.core.config import settings


engine = create_async_engine(
    settings.DB_ASYNC_URI,
    echo=False,
    max_overflow=10,
    # 🔥 关键配置：开启预检查，彻底解决 server closed connection 报错
    pool_pre_ping=True,
    # 以此配置，SQLAlchemy 会自动处理断开的连接
    pool_size=20,
    pool_recycle=3600,
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False, index=True)
    role = Column(String(50), nullable=False)  # 'user' or 'ai'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
