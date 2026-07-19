---
trigger: on_demand
description: ms-py-agent Python 规范（已拆分）。深度参考见 skills/agent-reference/SKILL.md
---

# Python 架构与代码规范指南

## 1. 基础构建块
* 类型检查： 领域层代码必须 100% 包含 Type Hints（类型提示）。
* 类定义： 优先使用 Python 标准库的 @dataclass 或第三方库 Pydantic (BaseModel) 来定义领域对象。
* ORM 隔离： 领域模型绝对不能继承自 sqlalchemy.Model、django.db.models.Model 等任何 ORM 基类。

## 2. 实体 (Entity) 规范
* 使用 @dataclass(eq=False) 声明。
* 必须手动实现 __eq__ 和 __hash__，并且仅通过唯一标识符（如 id 或 uuid）来判断实体是否相等。
* 业务校验规则必须放置在 __post_init__ 魔术方法中，或者在 Pydantic 的 @field_validator 中，确保对象一旦创建即是合法状态。

## 3. 值对象 (Value Object) 规范
* 必须使用 @dataclass(frozen=True) 声明，保证其不可变性。尝试修改值对象的属性必须在运行时引发异常。
* 对于金额、地址、坐标等概念，必须封装为值对象，严禁在领域实体中直接散落 latitude: float, longitude: float 这样的原生类型字段。

## 4. 异常处理规范 (Error Handling)
* **精准捕获**: 严禁使用空的 `try-except` 或模糊的 `except Exception:`。必须明确捕获预期的异常类型（如 `ValueError`, `KeyError`, `httpx.HTTPError`）。
* **禁止静默失败**: 除非有明确的业务降级逻辑，否则严禁在 `except` 块中仅使用 `pass`。必须记录 `logger.error` 或 `logger.warning`。
* **防御性编程**: 对 Nacos 配置下发等外部输入必须进行类型校验与转换异常处理。

## 5. MCP 客户端开发规范
* **类型安全**: 所有的 `MCPClient` 方法（如 `list_tools`, `call_tool`）必须包含完整的 Type Hints。
* **URL 约定**: 远程 MCP 调用必须遵循 `/mcp/messages` 的标准消息处理路径。
* **生命周期**: 必须实现完善的初始化与连接状态管理，对于 Stdio 模式需处理 JSON 解析异常。

## 6. 配置管理规范
* **声明式配置**: `app/core/config.py` 中的 `Config` 类成员必须全部标注类型。
* **动态同步**: 在 `dynamic_config.py` 中执行类型转换时，必须对转换失败进行防御处理，避免配置注入导致应用崩溃。