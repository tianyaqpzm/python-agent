from typing import Annotated, TypedDict, List
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from app.core.database import ChatMessageModel
from app.core.llm_factory import LLMFactory
from app.core.dynamic_config import dynamic_config
from app.services.mcp_client import mcp_clients, get_all_tools
from app.services.kb.retrieval import RetrievalService
from app.services.prompt_service import prompt_service
import logging
import json

logger = logging.getLogger(__name__)

# 1. 定义状态
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# 2. 动态构造 LangChain 工具包装器
async def execute_mcp_tool(name: str, arguments: dict, config: RunnableConfig):
    """
    通用工具执行器，支持 Token 透传。
    """
    # 从 config 中提取透传地址和 Token
    auth_header = config.get("configurable", {}).get("auth_header")
    headers = {"Authorization": auth_header} if auth_header else {}
    
    # 在所有注册的客户端中寻找目标工具 (Java 逻辑通过 NacosSSEMCPClient 处理)
    for client_name, client in mcp_clients.items():
        # 简单通过 client_name 匹配，或者通过 list_tools 的结果匹配
        # 这里为了简化，我们假设工具名包含了客户端特征或直接尝试匹配
        # 在 connect_clients 中我们会把所有工具注入到 llm
        pass
    
    # 实际执行逻辑见下方 get_tools 的封装
    pass

def create_mcp_langchain_tool(mcp_tool_def, client):
    """
    将 MCP 工具定义转换为 LangChain 的 @tool。
    """
    name = mcp_tool_def["name"]
    description = mcp_tool_def.get("description", f"Call {name}")
    
    @tool(name=name)
    async def wrapper(arguments: dict, config: RunnableConfig):
        # 这里的 arguments 是 LLM 生成的参数
        auth_header = config.get("configurable", {}).get("auth_header")
        headers = {"Authorization": auth_header} if auth_header else {}
        
        logger.info(f"🛠️ Executing MCP Tool [{name}] with token relay...")
        result = await client.call_tool(name, arguments, headers=headers)
        return json.dumps(result, ensure_ascii=False)
    
    wrapper.description = description
    return wrapper

# 3. 节点定义
async def agent_node(state: ChatState, config: RunnableConfig):
    # a. 获取最新的 LLM 配置
    provider = dynamic_config.llm_provider
    base_url = dynamic_config.llm_base_url
    model = dynamic_config.llm_model
    api_key = dynamic_config.llm_api_key

    # b. 动态获取所有 MCP 工具并绑定
    raw_tools = await get_all_tools()
    tools = []
    for t in raw_tools:
        client_name = t.get('client_name')
        client = mcp_clients.get(client_name)
        if client:
            tools.append(create_mcp_langchain_tool(t, client))

    # c. 初始化 LLM 并绑定工具
    llm = LLMFactory.get_llm(
        provider=provider, base_url=base_url, model_name=model, api_key=api_key
    )
    if tools:
        llm = llm.bind_tools(tools)

    messages = state["messages"]

    # d. RAG 增强 (保持原有逻辑)
    topic_id = config.get("configurable", {}).get("topic_id")
    if topic_id:
        try:
            ret_svc = RetrievalService()
            user_query = messages[-1].content if messages else ""
            if user_query:
                context_docs = await ret_svc.search(query=user_query, category=topic_id, top_k=5)
                if context_docs:
                    context_str = "\n---\n".join([d.get("content", "") for d in context_docs])
                    
                    # 🔥 动态 Prompt 管理：从数据库获取人格模板
                    prompt_slug = 'chef_persona_rag' if topic_id == 'topic_recipe_001' else 'default_kb_assistant'
                    prompt_data = await prompt_service.get_active_prompt(prompt_slug)
                    
                    if prompt_data:
                        # 渲染模板变量
                        system_prompt = prompt_service.render_prompt(
                            prompt_data['content'], 
                            {'context': context_str}
                        )
                        # TODO: 可以在这里应用 prompt_data['modelConfig'] 中的温度等参数
                    else:
                        # Fallback 逻辑
                        persona_prompt = "You are a helpful assistant."
                        system_prompt = f"{persona_prompt}\n\nContext:\n{context_str}"

                    messages = [SystemMessage(content=system_prompt)] + messages
        except Exception as e:
            logger.error(f"RAG or Dynamic Prompt failed: {e}")

    # e. 调用 LLM
    response = await llm.ainvoke(messages)
    return {"messages": [response]}

# 4. 路由逻辑
def should_continue(state: ChatState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

# 5. 构建图
workflow = StateGraph(ChatState)

# 动态加载工具用于 ToolNode
async def get_tools_instance():
    raw_tools = await get_all_tools()
    tools = []
    for t in raw_tools:
        client = mcp_clients.get(t.get('client_name'))
        if client:
            tools.append(create_mcp_langchain_tool(t, client))
    return tools

# 这是一个技巧：我们需要在运行时根据注册的工具创建 ToolNode
# 考虑到动态性，我们先定义节点
async def tool_node(state: ChatState, config: RunnableConfig):
    tools = await get_tools_instance()
    node = ToolNode(tools)
    return await node.ainvoke(state, config)

workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

async def save_chat_history(session, session_id, human_msg, ai_msg):
    try:
        user_msg = ChatMessageModel(session_id=session_id, role="user", content=human_msg)
        ai_p_msg = ChatMessageModel(session_id=session_id, role="ai", content=ai_msg)
        session.add(user_msg)
        session.add(ai_p_msg)
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e
