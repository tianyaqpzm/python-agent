from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.services.mcp_client import get_all_tools, mcp_clients
import json

# Placeholder for RAG
async def retrieve(state: AgentState):
    # Simulating RAG retrieval
    query = state['messages'][-1].content
    # In reality, query vector DB
    context = f"Retrieved context for: {query}"
    return {"context": context}

# Placeholder for LLM / Think
async def think(state: AgentState):
    messages = state['messages']
    context = state.get('context', '')
    
    # Simple logic to simulate "thinking"
    last_msg = messages[-1].content.lower()
    
    # If user asks to "search", we trigger tool call
    if "search" in last_msg:
        # Mocking a tool call decision
        return {"current_step": "tool_call", "tool_calls": [{"name": "brave-search", "args": {"q": "search term"}}]} 
    
    return {"current_step": "generate"}

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
    return {"messages": [AIMessage(content=f"Generated response based on: {context}")]}

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
