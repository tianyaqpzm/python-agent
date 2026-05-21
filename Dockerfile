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

# 安装系统依赖及 Node.js (使用最新 LTS 22.x 版本，支持 npx MCP 插件)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 复制依赖文件 (使用 uv 相关文件)
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖
# 使用 --system 安装到系统环境，因为是在容器内
RUN uv pip install --system --no-cache --no-cache-dir -r pyproject.toml

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
