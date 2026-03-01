from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from app.core.database import ChatMessageModel
from app.core.llm_factory import LLMFactory
from app.core.dynamic_config import dynamic_config
import logging

logger = logging.getLogger(__name__)


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# Remove global LLM init
# llm = ...


# Define a simple graph
async def agent_node(state: ChatState):
    # Retrieve latest config
    provider = dynamic_config.llm_provider
    base_url = dynamic_config.llm_base_url
    model = dynamic_config.llm_model

    # Initialize LLM on the fly (or use a cached factory if performance matters)
    # For now, we create a new instance to ensure config changes take effect immediately
    llm = LLMFactory.get_llm(provider=provider, base_url=base_url, model_name=model)

    # Call the LLM
    response = await llm.ainvoke(state["messages"])
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
