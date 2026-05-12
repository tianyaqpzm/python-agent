"""
A2A 远端 Agent 子图（模式 B）

通过 Agent-to-Agent (A2A) 协议将请求委托给外部 Agent 处理。

A2A 协议标准（Google 主导，2025）：
  https://google.github.io/A2A/

标准 Task API：
  POST /a2a/tasks/send     → 创建任务，返回 Task 对象（含 task_id）
  GET  /a2a/tasks/{id}     → 查询任务状态（SSE 流式 or 轮询）
  POST /a2a/tasks/{id}/cancel → 取消任务

当前实现状态：
  - 子图结构、状态字段、节点编排：✅ 完整
  - Nacos 服务发现：✅ 复用现有 nacos_manager
  - A2A HTTP 调用（send / poll）：🚧 pass 占位，待协议确认后实现
  - Token 透传：✅ auth_header 字段已就位

扩展指引：
  1. 实现 _send_a2a_task() 替换 pass
  2. 实现 _poll_a2a_result() 替换 pass（支持 SSE 流式）
  3. 在 config.py 中注册远端 Agent 的 Nacos 服务名
  4. 在 mcp_initialization.py 中完成路由意图 → 服务名的映射
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END

from app.agent.state import RemoteAgentSubState

logger = logging.getLogger(__name__)

# ── A2A 路由配置：intent → Nacos 服务名 ──────────────────────────────────────
# 后续在此扩展新的远端 Agent 映射，无需改动路由逻辑
_INTENT_TO_AGENT: Dict[str, str] = {
    # "coding": "ms-coding-agent",   # 示例：Coding 意图委托给专用编码 Agent
    # "analysis": "ms-data-agent",   # 示例：数据分析 Agent
}

# 默认远端 Agent（未在映射中命中时使用）
_DEFAULT_REMOTE_AGENT = "ms-remote-agent"


# ── 服务发现 ──────────────────────────────────────────────────────────────────

async def _resolve_agent_url(service_name: str) -> Optional[str]:
    """
    通过 Nacos 动态发现远端 Agent 地址。

    Args:
        service_name: Nacos 注册的服务名（如 "ms-java-agent"）

    Returns:
        服务基础 URL（如 "http://192.168.1.1:8080"），发现失败返回 None
    """
    try:
        from app.core.nacos import nacos_manager
        instances = nacos_manager.get_service(service_name)
        if not instances:
            logger.error("❌ A2A: No healthy instances for '%s' in Nacos.", service_name)
            return None
        instance = instances[0]
        return f"http://{instance['ip']}:{instance['port']}"
    except Exception as exc:
        logger.error("❌ A2A: Nacos discovery failed for '%s': %s", service_name, exc)
        return None


# ── A2A 协议核心操作（🚧 pass 占位，待实现）────────────────────────────────────

async def _send_a2a_task(
    agent_url: str,
    user_text: str,
    session_id: str,
    handoff_context: Optional[str],
    auth_header: Optional[str],
) -> Optional[str]:
    """
    🚧 [A2A] 向远端 Agent 发送任务（待实现）。

    标准请求体（A2A Task 格式）：
    {
        "id": "<uuid>",
        "sessionId": "<session_id>",
        "message": {
            "role": "user",
            "parts": [
                {"type": "text", "text": "<user_text>"},
                // 若有 handoff_context，追加为额外 part
            ]
        }
    }

    Args:
        agent_url:        远端 Agent 基础 URL
        user_text:        用户输入文本
        session_id:       会话 ID（来自 LangGraph thread_id）
        handoff_context:  本地子图产出的中间上下文（可选）
        auth_header:      JWT Token，透传给远端 Agent

    Returns:
        远端 Agent 创建的 task_id，失败返回 None
    """
    # TODO: 实现 A2A Task 创建
    # async with httpx.AsyncClient() as client:
    #     payload = {
    #         "id": str(uuid4()),
    #         "sessionId": session_id,
    #         "message": {
    #             "role": "user",
    #             "parts": [{"type": "text", "text": user_text}],
    #         },
    #     }
    #     if handoff_context:
    #         payload["message"]["parts"].append(
    #             {"type": "text", "text": f"[Context]\n{handoff_context}"}
    #         )
    #     headers = {"Authorization": auth_header} if auth_header else {}
    #     resp = await client.post(
    #         f"{agent_url}/a2a/tasks/send", json=payload, headers=headers, timeout=10.0
    #     )
    #     resp.raise_for_status()
    #     return resp.json()["id"]
    pass


async def _poll_a2a_result(
    agent_url: str,
    task_id: str,
    auth_header: Optional[str],
) -> Optional[str]:
    """
    🚧 [A2A] 轮询远端 Agent 任务结果（待实现）。

    支持两种模式：
    1. SSE 流式：GET /a2a/tasks/{id}，监听 "artifact" 事件
    2. 短轮询：GET /a2a/tasks/{id}，检查 status == "completed"

    Args:
        agent_url:   远端 Agent 基础 URL
        task_id:     由 _send_a2a_task 返回的任务 ID
        auth_header: JWT Token

    Returns:
        任务完成后的文本结果，失败或超时返回 None
    """
    # TODO: 实现 A2A 结果轮询（推荐 SSE 流式）
    # async with httpx.AsyncClient() as client:
    #     headers = {"Authorization": auth_header} if auth_header else {}
    #     async with client.stream(
    #         "GET", f"{agent_url}/a2a/tasks/{task_id}", headers=headers, timeout=60.0
    #     ) as response:
    #         async for line in response.aiter_lines():
    #             if line.startswith("data:"):
    #                 event_data = json.loads(line[5:])
    #                 if event_data.get("status") == "completed":
    #                     artifacts = event_data.get("artifacts", [])
    #                     return artifacts[0].get("parts", [{}])[0].get("text", "")
    pass


async def _cancel_a2a_task(
    agent_url: str,
    task_id: str,
    auth_header: Optional[str],
) -> None:
    """
    🚧 [A2A] 取消远端 Agent 任务（待实现）。

    Args:
        agent_url:   远端 Agent 基础 URL
        task_id:     要取消的任务 ID
        auth_header: JWT Token
    """
    # TODO: 实现 A2A 任务取消
    # async with httpx.AsyncClient() as client:
    #     headers = {"Authorization": auth_header} if auth_header else {}
    #     await client.post(
    #         f"{agent_url}/a2a/tasks/{task_id}/cancel", headers=headers, timeout=5.0
    #     )
    pass


# ── 子图节点 ──────────────────────────────────────────────────────────────────

async def remote_agent_node(
    state: RemoteAgentSubState, config: RunnableConfig
) -> Dict[str, Any]:
    """
    A2A 远端 Agent 委托节点。

    执行流程：
    1. 通过意图（intent）查找目标 Agent 的 Nacos 服务名
    2. Nacos 服务发现，获取远端 Agent 地址
    3. 发送 A2A Task（_send_a2a_task）
    4. 轮询/流式获取结果（_poll_a2a_result）
    5. 将结果包装为 AIMessage 写回 state

    注意：当前 Step 3/4 为 pass 占位，节点会返回 placeholder 响应。
    """
    # ── 1. 提取用户文本 ────────────────────────────────────────────────────
    from langchain_core.messages import HumanMessage
    messages = state.get("messages", [])
    user_text = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_text = m.content if isinstance(m.content, str) else str(m.content)
            break

    intent = state.get("intent", "general")
    auth_header = state.get("auth_header") or config.get("configurable", {}).get("auth_header")
    handoff_context = state.get("handoff_context")
    session_id = config.get("configurable", {}).get("thread_id", str(uuid4()))

    # ── 2. 查找目标 Agent 服务名 ────────────────────────────────────────────
    agent_service = _INTENT_TO_AGENT.get(intent or "", _DEFAULT_REMOTE_AGENT)
    logger.info(
        "🌐 A2A: delegating intent='%s' → service='%s'", intent, agent_service
    )

    # ── 3. Nacos 服务发现 ───────────────────────────────────────────────────
    agent_url = await _resolve_agent_url(agent_service)
    if not agent_url:
        error_msg = f"[A2A] 远端 Agent '{agent_service}' 暂不可用，请稍后重试。"
        logger.error("❌ A2A: Cannot resolve '%s', returning error response.", agent_service)
        return {
            "messages": [AIMessage(content=error_msg)],
            "handled_by": f"remote:{agent_service}@unavailable",
            "a2a_task_id": None,
            "artifacts": [],
        }

    # ── 4. 发送 A2A Task（🚧 pass 占位）───────────────────────────────────
    task_id: Optional[str] = await _send_a2a_task(
        agent_url=agent_url,
        user_text=user_text,
        session_id=session_id,
        handoff_context=handoff_context,
        auth_header=auth_header,
    )

    # ── 5. 获取 A2A 结果（🚧 pass 占位）───────────────────────────────────
    result_text: Optional[str] = None
    if task_id:
        result_text = await _poll_a2a_result(
            agent_url=agent_url,
            task_id=task_id,
            auth_header=auth_header,
        )

    # ── 6. 构造响应（pass 阶段使用 placeholder）────────────────────────────
    if result_text:
        response_msg = AIMessage(content=result_text)
        artifacts = [{"source": agent_service, "type": "text", "content": result_text}]
    else:
        # 🚧 A2A 未实现时的 placeholder 响应
        response_msg = AIMessage(
            content=(
                f"[A2A Remote Agent — 🚧 待实现]\n\n"
                f"已识别委托目标：{agent_service} ({agent_url})\n"
                f"用户请求：{user_text}\n\n"
                f"A2A Task 创建与结果轮询逻辑待实现（见 remote_agent_graph.py）。"
            )
        )
        artifacts = []

    return {
        "messages": [response_msg],
        "handled_by": f"remote:{agent_service}@{agent_url}",
        "remote_agent_name": agent_service,
        "remote_agent_url": agent_url,
        "a2a_task_id": task_id,
        "artifacts": artifacts,
        "sources": [],
    }


# ── 子图构建 ──────────────────────────────────────────────────────────────────

def build_remote_agent_subgraph() -> StateGraph:
    """
    构建 A2A 远端 Agent 子图（未编译）。

    当前节点：
    - remote_agent: 服务发现 + A2A Task 委托（HTTP 调用待实现）

    后续扩展节点（在此追加）：
    - result_transformer: 将 A2A artifact 格式转换为前端友好格式
    - error_fallback:     A2A 失败时的本地降级处理

    Returns:
        未编译的 StateGraph
    """
    builder = StateGraph(RemoteAgentSubState)
    builder.add_node("remote_agent", remote_agent_node)
    builder.set_entry_point("remote_agent")
    builder.add_edge("remote_agent", END)
    return builder
