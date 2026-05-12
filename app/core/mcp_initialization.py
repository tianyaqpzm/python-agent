"""
MCP 客户端初始化

在 FastAPI lifespan 启动阶段：
1. 向 MCPToolRegistry 注册 MCP Server 配置
2. 调用 registry.setup() 建立连接并缓存工具 Schema

兼容策略：
- 新架构：优先使用 MCPToolRegistry（官方 mcp SDK）
- 旧架构：保留 mcp_clients 注册表，供 chat_graph.py 兼容使用

MCP Server 集成清单：
- [x] filesystem（官方，Stdio，本地文件系统操作）
- [x] ms-java-biz（SSE，企业业务工具，通过 Nacos 动态发现）
- [ ] sqlite（官方，Stdio，需用户提供 DB 路径）
- [ ] brave-search（Stdio，需 API Key）
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


async def setup_mcp_registry() -> None:
    """
    初始化 MCPToolRegistry（新架构入口）。

    1. 从 ms-java-biz 拉取已启用的插件列表
    2. 动态向 registry 注册这些插件
    3. 调用 registry.setup() 建立连接
    """
    from app.core.mcp_registry import mcp_tool_registry
    import httpx

    java_url = await _resolve_java_mcp_url()
    if not java_url:
        logger.warning("⚠️  Java service not found, using fallback local registration.")
        _register_fallbacks(mcp_tool_registry)
        await mcp_tool_registry.setup()
        return

    import time
    import uuid
    
    request_id = str(uuid.uuid4())[:8]
    start_time = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 获取已启用的插件 (Whitelist mode)
            logger.info("📡 [MCP-Init-%s] Fetching enabled MCP plugins from: %s/rest/biz/v1/mcp-plugins/enabled", 
                        request_id, java_url)
            
            response = await client.get(f"{java_url}/rest/biz/v1/mcp-plugins/enabled")
            duration = time.perf_counter() - start_time
            
            if response.status_code == 200:
                plugins = response.json()
                logger.info("✅ [MCP-Init-%s] Successfully fetched %d plugin(s) from Java service in %.2fs.", 
                            request_id, len(plugins), duration)
                
                if not plugins:
                    logger.warning("⚠️  [MCP-Init-%s] No enabled MCP plugins found in Java service.", request_id)
                
                for p in plugins:
                    name = p["name"]
                    p_type = p["type"]
                    config = p.get("config", {})
                    
                    if p_type == "sse":
                        # 处理相对路径 (如 /mcp/sse -> http://host:port/mcp/sse)
                        url = config.get("url")
                        if url and url.startswith("/"):
                            url = f"{java_url}{url}"
                        mcp_tool_registry.register_sse(name=name, url=url)
                    
                    elif p_type == "stdio":
                        mcp_tool_registry.register_stdio(
                            name=name,
                            command=config.get("command"),
                            args=config.get("args", []),
                            env=config.get("env")
                        )
                logger.info("✅ [MCP-Init-%s] Dynamically registered %d MCP plugin(s).", request_id, len(plugins))
            else:
                logger.warning("⚠️  [MCP-Init-%s] Failed to fetch MCP plugins (Status: %d) in %.2fs. Using fallbacks.", 
                               request_id, response.status_code, duration)
                _register_fallbacks(mcp_tool_registry)
    
    except Exception as e:
        duration = time.perf_counter() - start_time
        logger.error("❌ [MCP-Init-%s] Error fetching MCP plugins after %.2fs: %s. Using fallbacks.", 
                     request_id, duration, e)
        _register_fallbacks(mcp_tool_registry)

    # 统一建立连接
    await mcp_tool_registry.setup()


def _register_fallbacks(registry: Any) -> None:
    """本地备选注册逻辑，确保在 Java 服务不可用时仍有基础能力。"""
    npx_path = _find_npx()
    if npx_path:
        registry.register_stdio(
            name="filesystem",
            command=npx_path,
            args=["-y", "@modelcontextprotocol/server-filesystem", str(Path.cwd())],
        )
        logger.info("📁 Fallback: Registered filesystem MCP")


async def setup_mcp_clients() -> None:
    """
    兼容旧架构的初始化函数（供 lifecycle.py 调用）。
    同时初始化新 Registry 和旧 Client。
    """
    # 新架构：动态拉取并连接
    await setup_mcp_registry()

    # 旧架构兼容（供旧 chat_graph.py 使用，不影响新逻辑）
    _setup_legacy_clients()


def _setup_legacy_clients() -> None:
    """保留旧 mcp_clients 注册，防止旧代码崩溃。"""
    try:
        from app.services.mcp_client import NacosSSEMCPClient, register_mcp_client
        java_client = NacosSSEMCPClient(
            name="java-service",
            target_service_name=settings.NACOS_JAVA_SERVICE_NAME,
        )
        register_mcp_client(java_client)
    except Exception:
        pass


async def connect_clients() -> None:
    """旧架构后台任务：预解析 URL。"""
    try:
        from app.services.mcp_client import mcp_clients
        client = mcp_clients.get("java-service")
        if client and hasattr(client, "_resolve_url"):
            await client._resolve_url()
    except Exception:
        pass


def _find_npx() -> str | None:
    """查找 npx 可执行路径。"""
    if hasattr(settings, "MCP_BRAVE_PATH") and settings.MCP_BRAVE_PATH:
        return settings.MCP_BRAVE_PATH
    return shutil.which("npx")


async def _resolve_java_mcp_url() -> str | None:
    """通过 Nacos 动态发现 Java 服务地址。"""
    try:
        from app.core.nacos import nacos_manager
        instances = nacos_manager.get_service(settings.NACOS_JAVA_SERVICE_NAME)
        if not instances:
            return None
        instance = instances[0]
        return f"http://{instance.get('ip')}:{instance.get('port')}"
    except Exception:
        return None
