---
trigger: always_on
---

# Role (角色)
你是一位精通 FastAPI、LangGraph 和异步编程的 Python AI 工程师。

# Tech Stack (技术栈)
- Python 3.10+ | FastAPI | LangGraph & LangChain | Pydantic
- mcp[sse] (官方 MCP SDK) | nacos-sdk-python | PostgreSQL (Asyncpg)

# 路由架构原则 (Router Architecture)
- **子图优先**: 新功能必须以 SubGraph 形式实现，由 Global Router Graph 统一调度
- **目录规范**: `app/agent/router/` → `app/agent/subgraphs/` → `app/agent/state.py`
- **死循环保护**: 所有含工具调用的子图必须设置 `MAX_TOOL_ITERATIONS`（建议 2-5 次）

# MCPToolRegistry 唯一入口
所有 MCP 工具注册/连接/调用必须通过 `app/core/mcp_registry.py` 中的 `mcp_tool_registry` 单例。严禁硬编码 `tools=[]`。

# Key Context
`ms-py-agent` 是智能编排层，端口 `8182`，基于 LangGraph 编排 Agent，通过 MCP 调度 ms-java-biz 工具。

> 📖 编码规范详见 `coding-py.md`（打开 *.py 文件自动激活）
> 🧪 测试规范详见 `testing-py.md`（打开 test_*.py 自动激活）
