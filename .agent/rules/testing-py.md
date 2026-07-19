---
trigger: glob
globs: ["**/test_*.py", "**/*_test.py"]
---

# Python 测试规范 (ms-py-agent)

## 1. 异常处理规范
- **严禁**空的 `try-except` 或模糊的 `except Exception:`
- 必须明确捕获预期异常类型（如 `ValueError`, `httpx.HTTPError`）
- 除非有明确降级逻辑，`except` 块中禁止仅使用 `pass`，必须记录 `logger.error`

## 2. 防御性编程
- 对 Nacos 配置下发等外部输入必须进行类型校验与转换异常处理

## 3. 领域对象测试
- Entity 测试：验证 `__eq__` 和 `__hash__` 仅基于 ID
- Value Object 测试：验证修改属性时抛出 `FrozenInstanceError`

## 4. MCP Client 测试
- 所有 `MCPClient` 方法（`list_tools`, `call_tool`）必须含完整 Type Hints
- Mock MCP 连接，不要在测试中真实发起 SSE 连接
