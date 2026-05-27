# 使用官方 Python 基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
# 防止 Python 生成pyc文件
ENV PYTHONDONTWRITEBYTECODE=1
# 防止 Python 缓冲 stdout 和 stderr
ENV PYTHONUNBUFFERED=1
ENV APP_PORT=8181
# 允许 uv 在容器的系统 Python 环境中安装包（无需虚拟环境）
ENV UV_SYSTEM_PYTHON=1

# 安装系统依赖及 Node.js (使用最新 LTS 22.x 版本，支持 npx MCP 插件)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 复制依赖文件 (使用 uv 相关文件，包含 README.md 以供 uv sync 读取项目元数据)
COPY pyproject.toml uv.lock README.md ./

# 安装 Python 依赖
# 冻结依赖版本、排除开发依赖、仅安装依赖而不安装项目本身
RUN uv sync --frozen --no-dev --no-install-project

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE $APP_PORT

# 创建非 root 用户运行
RUN useradd -m myuser \
    && mkdir -p /app/logs \
    && chown -R myuser:myuser /app/logs
USER myuser

# 启动命令
# 使用 uvicorn 直接启动，生产环境不需要 --reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8181"]
