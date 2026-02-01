import os
import shutil
import sys
import asyncio
from app.services.mcp_client import StdioMCPClient, SSEMCPClient, register_mcp_client
from app.core.nacos import nacos_manager
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

async def setup_mcp_clients():
    # 1. Stdio Client (e.g., Brave Search)
    # We'll use a placeholder command or the one requested if we can find it.
    # The user mentioned "Node.js MCP Server (如 Brave Search)".
    # Let's assume the user has npx and the package.
    
    # Check config first, then fall back to auto-discovery
    npx_path = settings.MCP_BRAVE_PATH or shutil.which("npx")

    # 2. 安全检查：如果没有安装 Node.js/npx，提前报错
    if not npx_path:
        raise FileNotFoundError("未找到 npx 命令，请确保已安装 Node.js 并添加到环境变量中，或在配置中指定路径。")

    # 3. 初始化客户端
    brave_client = StdioMCPClient(
        name="brave-search",
        command=npx_path,  # 传入绝对路径，如 "C:\...\npx.cmd"
        args=["-y", "@modelcontextprotocol/server-brave-search"]
    )
    # We register it but connection happens async
    # await brave_client.connect() # Connect in background
    register_mcp_client(brave_client)
    
    # 2. SSE Client (Java Service)
    # Discover via Nacos
    # In a real app we might poll or wait for service to be available.
    # Here we'll try once or assume fixed path for testing if not found.
    # Wait, the java service is running? User said "run time query".
    pass

async def connect_clients():
    # Connect Stdio
    try:
        # We need to find the client from registry
        from app.services.mcp_client import mcp_clients
        if "brave-search" in mcp_clients:
            await mcp_clients["brave-search"].connect()
    except Exception as e:
        logger.error(f"Failed to connect to Brave Search: {e}")

    # Connect SSE
    try:
        # Resolve Java service
        instances = nacos_manager.get_service(settings.NACOS_GATEWAY_SERVICE_NAME)
        if instances:
            # Pick one
            target = instances[0]
            ip = target['ip']
            port = target['port']
            url = f"http://{ip}:{port}"
            sse_client = SSEMCPClient(name="java-service", base_url=url)
            # await sse_client.connect()
            register_mcp_client(sse_client)
            logger.info(f"Registered SSE client for Java service at {url}")
        else:
            logger.warning(f"No {settings.NACOS_GATEWAY_SERVICE_NAME} service found in Nacos")
    except Exception as e:
        logger.error(f"Failed to setup SSE client: {e}")
