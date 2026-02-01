from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager
from app.core.nacos import nacos_manager
from app.setup import setup_mcp_clients, connect_clients
from app.agent.graph import graph
from langchain_core.messages import HumanMessage
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 定义一个全局集合，用来存放后台任务的引用，防止被 GC
background_tasks = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Agent starting up...")
    nacos_manager.register_service()
    
    # Setup and connect MCP clients
    await setup_mcp_clients()
    # connect_clients needs to run after startup potentially or concurrency
    task = asyncio.create_task(connect_clients())
    background_tasks.add(task)
    # 当任务完成时，自动从集合中移除，避免内存泄漏
    task.add_done_callback(background_tasks.discard)

    yield
    # Shutdown logic
    logger.info("Agent shutting down...")
    nacos_manager.deregister_service()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        inputs = {"messages": [HumanMessage(content=request.message)]}
        result = await graph.ainvoke(inputs)
        # Extract final message
        last_message = result['messages'][-1]
        return {"response": last_message.content, "state": result}
    except Exception as e:
        logger.error(f"Error during chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
