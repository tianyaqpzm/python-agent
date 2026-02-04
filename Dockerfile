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

# 安装系统依赖 (如果需要 pg_config 等，可能需要 install libpq-dev gcc)
# psycopg[binary] 通常包含二进制，slim 镜像一般能直接用，如果报错再加
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE $APP_PORT

# 创建非 root 用户运行
RUN useradd -m myuser
USER myuser

# 启动命令
# 使用 uvicorn 直接启动，生产环境不需要 --reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8181"]
