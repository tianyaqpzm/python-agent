from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.agent.factory import get_graph_runnable
from app.services.chat_graph import save_chat_history
from app.core.database import AsyncSessionLocal, get_lg_pool
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

@router.post("/chat")
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    async def event_generator():
        try:
            # 发送一个初始握手信号，确认连接已建立且生成器已启动
            yield ": connected\n\n"

            # 1. 按需同步当前用户启用的 MCP 插件
            try:
                from app.core.mcp_initialization import sync_mcp_with_user
                await sync_mcp_with_user(user_id=current_user.id)
            except Exception as e:
                logger.error(f"⚠️ MCP User Sync failed: {e}")
                # 继续执行，可能还有静态工具可用
            try:
                # 获取编译好的 Graph (直接获取连接池)
                pool = await get_lg_pool()
                graph = await get_graph_runnable(pool)

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
                    # 1. 捕获流式 Token (用于实时渲染)
                    if kind == "on_chat_model_stream":
                        content = event["data"]["chunk"].content
                        if content:
                            yield f"data: {json.dumps({'content': content})}\n\n"
                    
                    # 2. 捕获最终结果 (用于持久化)
                    # 由于采用了路由架构，最终输出可能来自不同的子图节点
                    elif kind == "on_chain_end" and event["name"] in [
                        "agent", "rag_subgraph", "general_subgraph", "coding_subgraph"
                    ]:
                        output = event["data"]["output"]
                        if output and "messages" in output and output["messages"]:
                            final_response = output["messages"][-1].content
                            
                            # 提取并发送引用来源
                            sources = output.get("sources", [])
                            if sources:
                                yield f"data: {json.dumps({'sources': sources})}\n\n"
                            
                            logger.info(f"Captured final response from {event['name']}: {final_response[:50]}...")


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
