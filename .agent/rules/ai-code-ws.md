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
   - **超时配置**: SSE 模式下必须显式设置 `timeout` (建议 30s+) 和 `sse_read_timeout` (建议 300s+)，避免 httpx 默认 5s 超时。
   - **调用保护**: 工具执行必须包裹在超时控制内（如 `asyncio.wait_for`），并记录耗时日志。
   - **自动重试**: 必须捕获 `RemoteProtocolError` (incomplete chunked read) 并在 re-connect 后至少执行一次自动重试，以对抗 VPN 链路抖动。
   - 必须优雅地处理 SSE 断线重连逻辑。

4. **API 设计**:
   - 通过 FastAPI 暴露接口。
   - 聊天接口必须使用 `StreamingResponse`，将 LLM/LangGraph 生成的 Token 实时流式转发给网关。

5. **领域层与类型安全 (Domain & Typing)**:
   - **领域隔离**: 领域模型必须是纯 POJO (使用 `@dataclass`)，严禁继承 ORM 基类。参考 [CODING_STANDARDS.md](./CODING_STANDARDS.md)。
   - **实体与值对象**: 
     - **实体 (Entity)**: 必须使用 `@dataclass(eq=False)`，并手动实现基于 ID 的 `__eq__` 和 `__hash__`。
     - **值对象 (Value Object)**: 必须使用 `@dataclass(frozen=True)`，依靠默认的值相等性判断。
   - **100% 类型覆盖**: 核心业务逻辑与方法签名必须包含完整的 Type Hints。
   - **异常处理**: 严禁空捕获，必须精准捕获具体异常并记录有效日志。

6. **数据库与通信规范 (DB & Communication)**:
   - **表名对齐**: 持久化模型表名必须严格遵循 Java 后端迁移脚本（Flyway）定义的命名规范（如 `ms_chat_message`），以确保触发器正常生效。
   - **Token 透传 (Token Relay)**: 所有发往业务后端（如 `ms-java-biz`）的 MCP 请求必须显式从 `RunnableConfig` 提取 `Authorization` 头并进行透传。
   - **动态工具发现**: 使用 `StructuredTool.from_function` 替代 `@tool` 装饰器，以支持动态设置工具名称（name）和描述（description）。

7. **流式与状态同步 (Streaming & State Sync)**:
   - **显式流式**: `LLMFactory` 创建模型时必须显式设置 `streaming=True`，否则 `astream_events` 无法产生 `on_chat_model_stream` 事件。
   - **事件监听**: `StreamingResponse` 应优先捕获 `on_chat_model_stream` 增量 Token，而非仅等待 `on_chain_end` 全量结果。
   - **状态截断意识**: 在使用 LangGraph Checkpointer 时，需意识到前端重试可能导致后端状态堆积。设计 API 时应考虑支持显式的历史截断（Rewind）逻辑。

# Key Context (关键背景)
本服务 (`ms-py-agent`) 是智能编排层。它基于 LangGraph 编排 Agent 工作流对接 LLM 进行推理与规划，并在需要执行业务操作时，通过 MCP 协议动态调度 `ms-java-biz` 提供的工具。它同时在数据库中维护对话上下文 (Memory)。

## 8. 路由架构规范 (Router Architecture)

> 2026-05-10 引入：单体图 → 路由架构重构

- **路由图优先**: 新功能必须以**子图（SubGraph）**形式实现，由 Global Router Graph 统一调度，严禁在主图中堆叠业务节点。
- **目录规范**:
  - `app/agent/router/` — 路由图和路由节点（意图分类）
  - `app/agent/subgraphs/` — 各领域子图（RAG、Coding、General...）
  - `app/agent/state.py` — 全局 State（GlobalState）和子图专用 State（RagSubState 等）
- **意图分类策略**: `router_node` 优先使用关键词规则（保证测试确定性），未命中时 fallback 到 LLM 分类。
- **State 隔离**: 每个子图使用专属 TypedDict（如 `RagSubState`），子图不得访问其他子图的专属字段。
- **工厂函数约定**: `build_xxx_subgraph()` 返回**未编译**的 `StateGraph`，由父图或工厂统一编译后注入 Checkpointer。
- **死循环保护 (Circuit Breaker)**: 所有包含工具调用的子图必须设置 `MAX_TOOL_ITERATIONS`（建议 2-5 次），在 `should_continue` 逻辑中强制校验迭代次数，超限必须终止并记录 Warning 日志。

## 9. MCPToolRegistry 规范

> 替代手写 JSON-RPC 客户端，使用官方 mcp SDK

- **唯一入口**: 所有 MCP 工具的注册、连接、调用必须通过 `app/core/mcp_registry.py` 中的 `mcp_tool_registry` 单例。
- **严禁硬编码 `tools=[]`**: 工具列表在 lifespan 启动时由 `mcp_tool_registry.setup()` 动态加载，子图通过 `mcp_tool_registry.get_langchain_tools()` 获取。
- **生命周期绑定**: `setup()` 在 `lifespan` startup 中调用，`teardown()` 在 shutdown 中调用，确保连接资源正确释放。
- **兼容层**: `app/services/mcp_client.py` 中的旧 `mcp_clients` 注册表保留以兼容 `chat_graph.py`，新代码禁止直接使用。