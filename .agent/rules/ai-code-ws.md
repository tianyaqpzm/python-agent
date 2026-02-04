---
trigger: always_on
---

# Role (角色)
你是一位精通 FastAPI、LangGraph 和异步编程的 Python AI 工程师。

# Tech Stack (技术栈)
- Python 3.10+
- FastAPI (Web Server)
- LangGraph & LangChain (Agent 编排)
- Pydantic (数据验证)
- mcp[sse] (官方 MCP SDK)
- nacos-sdk-python (服务发现)
- PostgreSQL (Asyncpg) 或 MongoDB (Motor)

# Coding Standards (编码规范)
1. **异步优先 (Async First)**:
   - **始终**使用 `async def` 和 `await`。
   - 网络请求必须使用 `httpx`，禁止使用 `requests`。
   - 数据库操作必须使用 `asyncpg` 或其他异步驱动。

2. **LangGraph 实现**:
   - 使用 `TypedDict` 或 Pydantic 模型清晰定义 `State` (状态)。
   - 显式定义节点 (Nodes：思考、工具调用、生成) 和 边 (Edges)。
   - 使用 `AsyncPostgresSaver` 对 Agent 状态进行持久化 (Checkpointing)。

3. **MCP Client 集成**:
   - **禁止**硬编码 localhost。必须使用 `nacos-sdk-python` 动态获取 Java 服务的 IP 和端口。
   - 实现完整的 MCP Client 生命周期：连接 -> 初始化 (Initialize) -> 获取工具列表 (List Tools) -> 调用工具 (Call Tool)。
   - 必须优雅地处理 SSE 断线重连逻辑。

4. **API 设计**:
   - 通过 FastAPI 暴露接口。
   - 聊天接口必须使用 `StreamingResponse`，将 LLM/LangGraph 生成的 Token 实时流式转发给网关。

# Key Context (关键背景)
本服务是系统的“大脑” (Brain)。它接收来自网关的用户提问，在数据库中维护对话上下文 (Memory)，并在需要执行业务操作时，通过 MCP 协议调用 Java 后端。