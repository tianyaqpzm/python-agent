---
trigger: glob
globs: ["**/*.yaml", "**/*.yml", "**/*.toml"]
---

# 本地开发指南 (ms-py-agent)

## 服务配置
- **端口**: `8182`
- **VS Code 启动**: `.vscode/launch.json`

## AI 重启规范
重启服务时，必须读取 `.vscode/launch.json` 提取所需环境变量和 uvicorn 启动命令，确保 Nacos 等配置一致。

## 配置管理规范
- `app/core/config.py` 中的 `Config` 类成员必须全部标注类型
- `dynamic_config.py` 执行类型转换时，必须对转换失败进行防御处理，避免崩溃
