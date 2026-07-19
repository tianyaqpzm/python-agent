---
name: ms-py-agent-deep-reference
description: >
  ms-py-agent 完整规范深度参考。在以下场景下加载：
  - 需要了解 LangGraph 路由架构（SubGraph）的完整设计细节
  - 设计新的 SubGraph 时需要了解 State 隔离规范
  - 讨论 MCP Client 生命周期管理和断线重连策略
  - 需要了解 AsyncPostgresSaver Checkpointing 的完整用法
---

# ms-py-agent 完整规范参考

> 此文档是深度参考，日常编码请使用 Glob 触发的 `coding-py.md`

## 路由架构完整规范

### 目录结构
```
app/agent/
├── router/         # 路由图和路由节点（意图分类）
├── subgraphs/      # 各领域子图（RAG、Coding、General...）
└── state.py        # GlobalState + 子图专用 State（RagSubState 等）
```

### State 隔离规则
- 每个子图使用专属 TypedDict（如 `RagSubState`）
- 子图不得访问其他子图的专属字段

### 工厂函数约定
- `build_xxx_subgraph()` 返回**未编译**的 `StateGraph`
- 由父图或工厂统一编译后注入 Checkpointer

### 死循环保护
- 所有含工具调用的子图必须设置 `MAX_TOOL_ITERATIONS`（建议 2-5 次）
- `should_continue` 逻辑中强制校验迭代次数，超限终止并记录 Warning

## MCPToolRegistry 完整规范

```python
# 唯一入口
from app.core.mcp_registry import mcp_tool_registry

# lifespan
@asynccontextmanager
async def lifespan(app):
    await mcp_tool_registry.setup()      # startup
    yield
    await mcp_tool_registry.teardown()  # shutdown
```

- 子图通过 `mcp_tool_registry.get_langchain_tools()` 获取工具列表
- `app/services/mcp_client.py` 旧注册表仅兼容 `chat_graph.py`，新代码禁止直接使用

## 流式处理完整规范

```python
# 必须显式设置 streaming=True
model = LLMFactory.create(streaming=True)

# 优先捕获增量 Token
async for event in graph.astream_events(...):
    if event["event"] == "on_chat_model_stream":
        yield event["data"]["chunk"].content
```

## 数据库通信完整规范
- 持久化表名严格遵循 Flyway 定义的 `ms_` 前缀命名（如 `ms_chat_message`）
- 确保 PostgreSQL 触发器正常生效（Python 侧和 Java 侧表名必须完全一致）
