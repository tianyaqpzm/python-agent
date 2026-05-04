import asyncio
import time
import logging
from typing import Dict
from app.core.config import settings

logger = logging.getLogger(__name__)

class AsyncRateLimiter:
    """领域级基础限速器实现 (令牌桶算法)"""
    def __init__(self, rpm: int, name: str):
        self.name = name
        self.rpm = rpm
        self.rate = rpm / 60.0  # 每秒生成的令牌数
        self.capacity = rpm     # 桶容量
        self.tokens = float(rpm)
        self.last_updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1):
        """获取令牌。如果没有足够令牌，则异步等待。"""
        async with self.lock:
            while True:
                now = time.monotonic()
                # 补充令牌
                elapsed = now - self.last_updated
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.last_updated = now
                
                # 检查令牌是否足够
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                # 计算需要等待的时间
                wait_time = (tokens - self.tokens) / self.rate
                logger.debug(f"⏳ [RateLimiter:{self.name}] 限频中, 需等待 {wait_time:.2f}s")
                await asyncio.sleep(wait_time)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class LimiterRegistry:
    """
    公共限流注册中心。
    支持根据场景 Key 获取唯一的限流器，实现多场景资源隔离与策略共享。
    """
    _instances: Dict[str, AsyncRateLimiter] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_limiter(cls, scene: str, rpm: int) -> AsyncRateLimiter:
        """
        获取或创建一个限流器。
        :param scene: 场景标识 (例: "embedding:gemini", "chat:gpt-4")
        :param rpm: 对应的速率限制 (RPM)
        """
        async with cls._lock:
            # 如果配置有变动，这里也可以扩展出动态更新逻辑
            if scene not in cls._instances:
                logger.info(f"🆕 为场景 [{scene}] 初始化限流器 (RPM={rpm})")
                cls._instances[scene] = AsyncRateLimiter(rpm, scene)
            return cls._instances[scene]

# 便捷获取方法，供常用业务快速调用
async def get_llm_limiter():
    return await LimiterRegistry.get_limiter("llm:general", settings.LLM_RPM)

async def get_embedding_limiter():
    return await LimiterRegistry.get_limiter("embedding:general", settings.KB_EMBEDDING_RPM)
