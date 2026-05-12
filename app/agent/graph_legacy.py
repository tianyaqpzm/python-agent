from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.services.mcp_client import get_all_tools, mcp_clients
import json
from app.core.config import settings
import httpx

TOPIC_PERSONAS = {
    'topic_recipe_001': "你是一位拥有20年经验的中餐大厨，精通各大菜系。请用专业、亲切且热情的语气回答用户的菜谱相关问题，并提供实用的烹饪技巧。"
}

# Placeholder for RAG
async def retrieve(state: AgentState):
    # Simulating RAG retrieval based on topic_id
    query = state['messages'][-1].content
    topic_id = state.get('topic_id')
    
    context = f"关于 {query} 的背景知识"
    if topic_id == 'topic_recipe_001':
        # 这里以后可以调用 ms-java-biz 的检索接口
        context = f"菜谱库中关于 '{query}' 的推荐：东坡肉、清蒸鲈鱼等经典做法。"
        
    return {"context": context}

# Placeholder for LLM / Think
async def think(state: AgentState):
    messages = state['messages']
    topic_id = state.get('topic_id')
    
    # 根据 topic_id 注入人格
    persona = TOPIC_PERSONAS.get(topic_id, "你是一个通用的 AI 助手。")
    
    # 模拟 LLM 决策
    last_msg = messages[-1].content.lower()
    
    if "search" in last_msg:
        return {"current_step": "tool_call", "persona": persona} 
    
    return {"current_step": "generate", "persona": persona}

# Tool execution node
async def tool_call_node(state: AgentState):
    # This would parse the decision from 'think'
    # For now, we just list tools or call a mock one
    # Assuming 'think' decided to call a tool
    
    # Example: fetch all tools
    tools = await get_all_tools()
    
    # Mock execution
    # result = await client.call_tool(...)
    
    return {"messages": [AIMessage(content=f"Executed tool. Available tools: {len(tools)}")]}

# Generation node
async def generate(state: AgentState):
    context = state.get('context', '')
    persona = state.get('persona', '')
    query = state['messages'][-1].content
    
    # 模拟流式输出（实际上在这里应该调用 LLM SDK 并通过 SSE 返回）
    response_content = f"【{persona}】\n\n根据知识库内容：{context}\n\n关于您问的 '{query}'，我的建议是..."
    
    return {"messages": [AIMessage(content=response_content)]}

def route_step(state: AgentState):
    step = state.get('current_step')
    if step == "tool_call":
        return "tool_call"
    return "generate"

# Build Graph
builder = StateGraph(AgentState)

builder.add_node("retrieve", retrieve)
builder.add_node("think", think)
builder.add_node("tool_call", tool_call_node)
builder.add_node("generate", generate)

builder.set_entry_point("retrieve")

builder.add_edge("retrieve", "think")
builder.add_conditional_edges("think", route_step, {
    "tool_call": "tool_call",
    "generate": "generate"
})
builder.add_edge("tool_call", "generate") # Loop back or go to generate? User said "Tool Call -> Generate"
builder.add_edge("generate", END)

graph = builder.compile()
