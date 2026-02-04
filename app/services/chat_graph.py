from typing import Annotated, TypedDict
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from app.core.database import ChatMessageModel
import logging

logger = logging.getLogger(__name__)


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# Define a simple graph
def agent_node(state: ChatState):
    # Mock LLM logic for now
    last_message = state["messages"][-1]
    response = AIMessage(content=f"Echo: {last_message.content}")
    return {"messages": [response]}


workflow = StateGraph(ChatState)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)


async def save_chat_history(session, session_id, human_msg, ai_msg):
    # session 是 SQLAlchemy 的 AsyncSession
    try:
        user_msg = ChatMessageModel(
            session_id=session_id, role="user", content=human_msg
        )
        ai_msg = ChatMessageModel(session_id=session_id, role="ai", content=ai_msg)

        session.add(user_msg)
        session.add(ai_msg)

        await session.commit()  # 提交事务
    except Exception as e:
        await session.rollback()
        raise e
