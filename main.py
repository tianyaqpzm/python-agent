import sys
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

# 1. 基础配置：加载环境变量和初始化日志系统
load_dotenv()
from app.core.logging_config import setup_logging
setup_logging()

# ✋ 屏蔽 psycopg_pool 的 AsyncConnectionPool 弃用警告 (SQLAlchemy 内部触发)
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*opening the async pool AsyncConnectionPool in the constructor is deprecated.*")

logger = logging.getLogger(__name__)

# 2. Windows 兼容性补丁
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.config import settings
from app.core.lifecycle import lifespan
from app.api.routers import chat, kb

# 3. 创建 FastAPI 应用
app = FastAPI(
    title="ms-py-agent Service",
    lifespan=lifespan
)

# 注册路由
app.include_router(chat.router, tags=["chat"])
app.include_router(kb.router, prefix="/rest/kb/v1", tags=["Knowledge Base"])

from app.core.exception_handler import global_exception_handler
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(HTTPException, global_exception_handler)

@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"【Python请求】{request.method} {request.url.path}")
    response = await call_next(request)
    if response.status_code >= 400:
        logger.error(f"【Python响应异常】{request.method} {request.url.path} -> {response.status_code}")
    else:
        logger.info(f"【Python响应完成】{request.method} {request.url.path} -> {response.status_code}")
    return response

@app.get("/health")
async def health():
    return {"status": "ok"}

# 4. 启动入口
if __name__ == "__main__":
    print(f"🚀 Service starting with {asyncio.get_event_loop_policy().__class__.__name__}")
    
    # 注意：启动热重载时必须传字符串 "main:app"
    uvicorn.run(
        "main:app", 
        host=settings.HOST, 
        port=settings.PORT,
        reload=True if settings.APP_ENV == "development" else False
    )
