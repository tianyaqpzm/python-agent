---
trigger: glob
globs: ["**/*.py", "!**/test_*.py", "!**/*_test.py"]
---

# Python 编码规范 (ms-py-agent)

## 1. 异步优先 (Async First)
- 始终使用 `async def` 和 `await`
- 网络请求必须使用 `httpx`，**禁止** `requests`
- 数据库操作必须使用 `asyncpg` 或其他异步驱动

## 2. LangGraph 实现
- 使用 `TypedDict` 或 Pydantic 模型定义 `State`
- 显式定义节点（思考/工具调用/生成）和边
- 使用 `AsyncPostgresSaver` 持久化 Agent 状态（Checkpointing）

## 3. MCP Client 集成
- **禁止**硬编码 `localhost`；使用 `nacos-sdk-python` 动态获取 `ms-java-biz` 的 IP 和端口
- SSE 模式必须显式设置 `timeout`（建议 30s+）和 `sse_read_timeout`（建议 300s+）
- 工具执行必须包裹在 `asyncio.wait_for` 超时控制内，并记录耗时日志
- 必须捕获 `RemoteProtocolError`（incomplete chunked read）并在重连后自动重试一次

## 4. 流式处理
- `LLMFactory` 创建模型时必须显式设置 `streaming=True`
- `StreamingResponse` 优先捕获 `on_chat_model_stream` 增量 Token（而非等待 `on_chain_end`）

## 5. 领域层类型安全
- **Entity**: `@dataclass(eq=False)`，手动实现基于 ID 的 `__eq__` 和 `__hash__`
- **Value Object**: `@dataclass(frozen=True)`，依靠默认值相等性判断
- 核心业务逻辑必须 100% Type Hints，**严禁**空的 `except:` 块

## 6. Token 透传
所有发往 `ms-java-biz` 的 MCP 请求，必须显式从 `RunnableConfig` 提取 `Authorization` 头透传。

## 7. 动态工具发现
使用 `StructuredTool.from_function` 替代 `@tool` 装饰器，支持动态设置 `name` 和 `description`。
