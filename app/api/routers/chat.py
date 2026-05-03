from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.agent.factory import get_graph_runnable
from app.services.chat_graph import save_chat_history
from app.core.database import AsyncSessionLocal
from app.core.security import CurrentUser, get_current_user
from langchain_core.messages import HumanMessage
import json
import logging
from typing import Optional

# 1. 统一声明 Router 和 Logger
logger = logging.getLogger(__name__)
router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    topic_id: Optional[str] = None

@router.post("/rest/dark/v1/agent/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    # 拿到连接池
    lg_pool = getattr(request.app.state, "lg_pool", None)
    if not lg_pool:
        logger.error("lg_pool is not initialized in app state")
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': 'Internal server error: Database pool not initialized'})}\n\n"]),
            media_type="text/event-stream"
        )

    async def event_generator():
        try:
            # 发送一个初始握手信号，确认连接已建立且生成器已启动
            yield ": connected\n\n"
            
            final_response = ""
            try:
                # 获取编译好的 Graph (此时传入的是 pool，工厂内部会按需取放连接)
                graph = await get_graph_runnable(lg_pool)

                input_message = HumanMessage(content=body.message)
                # 提取授权头，用于后续透传给 Java MCP 服务
                auth_header = request.headers.get("Authorization")
                config = {
                    "configurable": {
                        "thread_id": body.session_id, 
                        "topic_id": body.topic_id,
                        "auth_header": auth_header
                    }
                }

                logger.info(f"Starting graph stream for session={body.session_id}")

                # 运行 Graph
                async for event in graph.astream_events(
                    {"messages": [input_message]}, config, version="v1"
                ):
                    kind = event["event"]
                    if kind == "on_chain_end" and event["name"] == "agent":
                        output = event["data"]["output"]
                        if output and "messages" in output and output["messages"]:
                            final_response = output["messages"][-1].content
                            logger.info(f"Captured final response: {final_response[:50]}...")
                            yield f"data: {json.dumps({'content': final_response})}\n\n"

            except Exception as e:
                logger.error(f"Processing error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

            # --- 历史记录保存 ---
            if final_response:
                try:
                    async with AsyncSessionLocal() as session:
                        await save_chat_history(
                            session, body.session_id, body.message, final_response
                        )
                except Exception as e:
                    logger.error(f"History save failed: {e}")

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Critical stream failure: {e}")
            yield f"data: {json.dumps({'error': 'Critical server error'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
