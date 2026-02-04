# 文件名: run.py
import sys
import asyncio
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# 🔥 1. 最关键的一步：在导入 Uvicorn 运行逻辑之前，强制修改 Windows 策略
# 这会影响当前进程
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    # 🔥 2. 启动 Uvicorn
    # 注意：在 Windows 上使用 SelectorLoop 时，reload=True 可能会在某些情况下失效或报错
    # 如果遇到子进程报错，建议暂时把 reload 改为 False 调试，或者忍受启动时的警告
    print(
        f"🚀 正在使用 {asyncio.get_event_loop_policy().__class__.__name__} 启动服务..."
    )

    uvicorn.run(
        "main:app",
        host="192.168.50.128",
        port=8181,
        reload=True,  # 开发环境开启热重载
    )
