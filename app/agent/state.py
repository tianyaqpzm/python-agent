"""
全局状态定义（Global State & SubState）

设计原则：
- GlobalState：路由图与所有子图共享的最小化状态
- 子图 State 继承 GlobalState 字段，并追加专属字段
- 使用 Annotated[list, add_messages] 保证消息追加语义

多 Agent 对接模式：
- 模式 A（本地子图）：rag / coding / general 子图，进程内执行
- 模式 B（A2A 远端）：remote_agent 子图，通过 HTTP 委托给外部 Agent
  A2A 协议参考：https://google.github.io/A2A/
"""
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ── Intent 类型（含 A2A 远端委托意图）─────────────────────────────────────────
IntentType = Literal["rag", "coding", "general", "remote_agent"]


class GlobalState(TypedDict):
    """
    全局路由图状态：贯穿所有子图的共享字段。

    字段分组：
    - 核心：messages, intent
    - 业务上下文：topic_id, auth_header, sources
    - 多 Agent 协作（A2A 扩展）：handled_by, a2a_task_id, artifacts, handoff_context
    """
    messages: Annotated[List[BaseMessage], add_messages]

    # ── 路由字段 ──────────────────────────────────────────────────────────────
    # 由 router_node 写入，驱动条件边选择子图
    intent: Optional[IntentType]

    # ── 业务上下文字段 ────────────────────────────────────────────────────────
    topic_id: Optional[str]       # 知识库/话题 ID，供 RAG 子图使用
    auth_header: Optional[str]    # JWT Token，透传给下游服务（MCP / A2A）
    sources: List[Dict[str, Any]] # RAG 引用来源，供前端渲染

    # ── 模式 A / B 通用协作字段（可选，子图写入，上游读取）──────────────────
    # 标识当前请求由哪个 agent 处理，格式：
    #   本地子图：  "local:rag"
    #   A2A 远端：  "remote:ms-java-agent@http://host:port"
    handled_by: Optional[str]

    # ── 模式 B：A2A 专用字段（本地子图不使用）──────────────────────────────
    # 远端 Agent 创建的任务 ID（用于查询状态 / 取消）
    a2a_task_id: Optional[str]

    # 远端 Agent 返回的结构化产出物（与 sources 语义不同：sources 是 RAG 来源）
    artifacts: List[Dict[str, Any]]

    # 多跳推理中的中间上下文（本地子图输出 → 作为远端 Agent 的输入前缀）
    handoff_context: Optional[str]


class RagSubState(TypedDict):
    """RAG 子图专用状态，包含向量检索上下文。"""
    messages: Annotated[List[BaseMessage], add_messages]
    intent: Optional[IntentType]
    topic_id: Optional[str]
    auth_header: Optional[str]
    sources: List[Dict[str, Any]]
    handled_by: Optional[str]
    artifacts: List[Dict[str, Any]]
    handoff_context: Optional[str]
    # RAG 专属字段
    context: Optional[str]            # 检索到的知识库片段
    rag_sources: List[Dict[str, Any]] # 原始引用文档列表


class CodingSubState(TypedDict):
    """Coding 子图专用状态。"""
    messages: Annotated[List[BaseMessage], add_messages]
    intent: Optional[IntentType]
    topic_id: Optional[str]
    auth_header: Optional[str]
    sources: List[Dict[str, Any]]
    handled_by: Optional[str]
    artifacts: List[Dict[str, Any]]
    handoff_context: Optional[str]
    # Coding 专属字段
    code_language: Optional[str]  # 目标编程语言（LLM 提取）
    code_result: Optional[str]    # 生成的代码结果


class RemoteAgentSubState(TypedDict):
    """
    A2A 远端 Agent 子图专用状态。

    完整继承 GlobalState 所有字段（包括 A2A 扩展字段），
    remote_agent_node 负责填充 a2a_task_id / artifacts 后写回 GlobalState。
    """
    messages: Annotated[List[BaseMessage], add_messages]
    intent: Optional[IntentType]
    topic_id: Optional[str]
    auth_header: Optional[str]
    sources: List[Dict[str, Any]]
    # A2A 协作字段（必填，由 remote_agent_node 写入）
    handled_by: Optional[str]
    a2a_task_id: Optional[str]
    artifacts: List[Dict[str, Any]]
    handoff_context: Optional[str]
    # A2A 专属字段
    remote_agent_name: Optional[str]  # 目标 Agent 的 Nacos 服务名
    remote_agent_url: Optional[str]   # 解析后的实际地址（含 scheme）


# 兼容旧代码：保留 AgentState 别名
AgentState = GlobalState
