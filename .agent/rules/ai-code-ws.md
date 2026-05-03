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
   - **禁止**硬编码 localhost。必须使用 `nacos-sdk-python` 动态获取 `ms-java-biz` 的 IP 和端口。
   - 实现完整的 MCP Client 生命周期：连接 -> 初始化 (Initialize) -> 获取工具列表 (List Tools) -> 调用工具 (Call Tool)。
   - 必须优雅地处理 SSE 断线重连逻辑。

4. **API 设计**:
   - 通过 FastAPI 暴露接口。
   - 聊天接口必须使用 `StreamingResponse`，将 LLM/LangGraph 生成的 Token 实时流式转发给网关。

5. **领域层与类型安全 (Domain & Typing)**:
   - **领域隔离**: 领域模型必须是纯 POJO (使用 `@dataclass`)，严禁继承 ORM 基类。参考 [CODING_STANDARDS.md](./CODING_STANDARDS.md)。
   - **100% 类型覆盖**: 核心业务逻辑与方法签名必须包含完整的 Type Hints。
   - **异常处理**: 严禁空捕获，必须精准捕获具体异常并记录有效日志。

6. **数据库与通信规范 (DB & Communication)**:
   - **表名对齐**: 持久化模型表名必须严格遵循 Java 后端迁移脚本（Flyway）定义的命名规范（如 `ms_chat_message`），以确保触发器正常生效。
   - **Token 透传 (Token Relay)**: 所有发往业务后端（如 `ms-java-biz`）的 MCP 请求必须显式从 `RunnableConfig` 提取 `Authorization` 头并进行透传。
   - **动态工具发现**: 使用 `StructuredTool.from_function` 替代 `@tool` 装饰器，以支持动态设置工具名称（name）和描述（description）。

# Key Context (关键背景)
本服务 (`ms-py-agent`) 是智能编排层。它基于 LangGraph 编排 Agent 工作流对接 LLM 进行推理与规划，并在需要执行业务操作时，通过 MCP 协议动态调度 `ms-java-biz` 提供的工具。它同时在数据库中维护对话上下文 (Memory)。