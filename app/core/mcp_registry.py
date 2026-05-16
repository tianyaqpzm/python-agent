"""
MCP 工具注册中心（基于官方 mcp SDK）

解决旧实现的扩展性问题：
- 旧方案：手写 JSON-RPC 客户端，工具列表硬编码 tools=[]
- 新方案：使用官方 mcp SDK 的 ClientSession，动态加载工具 Schema
         并封装为 LangChain StructuredTool，可直接绑定到 LLM

支持的 Server 类型：
- Stdio：本地可执行文件（如 filesystem、sqlite 官方 Server）
- SSE：远程 HTTP Server（如 ms-java-biz 的 MCP 接口）
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from langchain_core.runnables.config import RunnableConfig
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


@dataclass
class StdioServerConfig:
    """本地 Stdio MCP Server 配置。"""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    type: Literal["stdio"] = "stdio"


@dataclass
class SSEServerConfig:
    """远程 SSE MCP Server 配置。"""
    name: str
    url: str                           # SSE 握手端点，如 http://host/mcp/sse
    messages_url: Optional[str] = None # 消息端点，如 http://host/mcp/messages
    type: Literal["sse"] = "sse"


class _ClientEntry:
    """单个 MCP Server 连接条目，管理会话生命周期。"""

    def __init__(self, config: StdioServerConfig | SSEServerConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self._tools_cache: List[Dict[str, Any]] = []
        self._local_exit_stack: Optional[AsyncExitStack] = None
        self._reconnect_lock = asyncio.Lock()  # 防止并发重连
        self._is_alive = False

    async def connect(self) -> bool:
        """建立连接并初始化会话。确保先关闭旧连接。"""
        async with self._reconnect_lock:
            # 1. 彻底清理旧资源
            if self._local_exit_stack:
                try:
                    await self._local_exit_stack.aclose()
                except Exception as e:
                    logger.warning("Error closing old exit stack for [%s]: %s", self.config.name, e)
            
            self._local_exit_stack = AsyncExitStack()
            self.session = None
            self._is_alive = False

            try:
                await self._local_exit_stack.__aenter__()
                
                if self.config.type == "stdio":
                    params = StdioServerParameters(
                        command=self.config.command,
                        args=self.config.args,
                        env=self.config.env,
                    )
                    read, write = await self._local_exit_stack.enter_async_context(stdio_client(params))
                else:
                    sse_url = self.config.url
                    logger.info("📡 Connecting to SSE MCP Server [%s] at %s", self.config.name, sse_url)
                    # 调优 httpx 参数：增加 read_timeout
                    read, write = await self._local_exit_stack.enter_async_context(
                        sse_client(
                            sse_url, 
                            timeout=30.0, 
                            sse_read_timeout=600.0
                        )
                    )

                self.session = await self._local_exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await self.session.initialize()
                self._is_alive = True
                logger.info("✅ MCP Server [%s] connected and initialized.", self.config.name)
                return True
            except Exception as exc:
                self._is_alive = False
                logger.exception("❌ MCP Server [%s] connect failed: %s", self.config.name, exc)
                return False

    async def _ensure_connected(self) -> bool:
        """确保连接可用，如果已断开则尝试重连。"""
        if self._is_alive and self.session:
            return True
        return await self.connect()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表（含 Schema），缓存到实例。支持失败重试（含重连）。"""
        max_retries = 1
        last_error = None

        for attempt in range(max_retries + 1):
            # 确保会话存在
            if not self.session:
                if not await self.connect():
                    continue

            try:
                # 添加超时保护
                response = await asyncio.wait_for(self.session.list_tools(), timeout=15.0)
                self._tools_cache = [
                    {
                        "name": t.name,
                        "description": t.description or f"Call {t.name}",
                        "inputSchema": t.inputSchema or {},
                        "server_name": self.config.name,
                    }
                    for t in response.tools
                ]
                logger.info(
                    "🔧 MCP Server [%s] provides %d tool(s): %s (attempt %d)",
                    self.config.name,
                    len(self._tools_cache),
                    [t["name"] for t in self._tools_cache],
                    attempt + 1
                )
                return self._tools_cache

            except (asyncio.TimeoutError, Exception) as exc:
                last_error = exc
                error_msg = str(exc)
                error_type = type(exc).__name__
                
                # 如果是连接断开导致的错误，尝试重连并重试
                is_conn_error = any(msg in error_msg.lower() for msg in [
                    "closed", "connection", "eof", "incomplete"
                ]) or error_type in ["ClosedResourceError", "RemoteProtocolError"]

                if (is_conn_error or isinstance(exc, asyncio.TimeoutError)) and attempt < max_retries:
                    logger.warning("🚨 list_tools from [%s] failed (%s): %s. Retrying after reconnect...", 
                                   self.config.name, error_type, error_msg)
                    self._is_alive = False # 强制下次 connect 重新初始化
                    await self.connect()
                    continue
                
                if isinstance(exc, asyncio.TimeoutError):
                    logger.error("⏰ list_tools from [%s] timed out after 15s", self.config.name)
                else:
                    logger.error("❌ list_tools from [%s] failed after %d attempt(s): %s (Type: %s)", 
                                 self.config.name, attempt + 1, exc, error_type)
        
        return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_header: Optional[str] = None,
    ) -> Any:
        """调用指定工具，支持重连尝试。"""
        
        max_retries = 1
        last_error = None
        
        for attempt in range(max_retries + 1):
            # 1. 确保连接有效
            await self._ensure_connected()

            if not self.session:
                return {"error": f"MCP Server [{self.config.name}] is not connected."}

            try:
                import time
                start = time.perf_counter()
                from datetime import timedelta
                
                # 使用 wait_for 包裹调用
                result = await asyncio.wait_for(
                    self.session.call_tool(
                        tool_name,
                        arguments,
                        read_timeout_seconds=timedelta(seconds=30),
                    ),
                    timeout=35.0,
                )
                elapsed = time.perf_counter() - start
                logger.info("⏱️ call_tool [%s/%s] completed in %.2fs (attempt %d)", 
                            self.config.name, tool_name, elapsed, attempt + 1)
                
                if result.content:
                    content_parts = []
                    for c in result.content:
                        if hasattr(c, "text"):
                            content_parts.append(c.text)
                    return "\n".join(content_parts) if content_parts else str(result.content)
                return ""

            except (asyncio.TimeoutError, Exception) as exc:
                # 标记连接为失效，以便重连
                self._is_alive = False
                error_msg = str(exc)
                last_error = exc
                
                # 识别特定的连接关闭异常，准备重试
                is_conn_error = any(msg in error_msg.lower() for msg in [
                    "peer closed connection", 
                    "incomplete chunked read",
                    "connection closed"
                ])
                
                if is_conn_error and attempt < max_retries:
                    logger.warning("🚨 MCP Server [%s] connection error: %s. Retrying (%d/%d)...", 
                                   self.config.name, error_msg, attempt + 1, max_retries)
                    continue # 触发下一次循环（含 _ensure_connected）
                
                # 如果是超时或已达到最大重试次数，则报错
                if isinstance(exc, asyncio.TimeoutError):
                    logger.error("⏰ call_tool [%s/%s] timed out", self.config.name, tool_name)
                    return {"error": f"Tool '{tool_name}' execution timed out (35s)"}

                logger.error("❌ call_tool [%s/%s] failed after %d attempt(s): %s", 
                             self.config.name, tool_name, attempt + 1, error_msg)
                return {"error": error_msg}

        return {"error": f"Failed to execute tool after {max_retries} retries. Last error: {last_error}"}


class MCPToolRegistry:
    """
    MCP 工具注册中心（单例）。

    职责：
    1. 统一管理多个 MCP Server 的连接生命周期
    2. 聚合所有工具 Schema，缓存为 StructuredTool 列表
    3. 提供按 server_name / tool_name 查找的工具执行接口
    """

    def __init__(self) -> None:
        self._configs: Dict[str, StdioServerConfig | SSEServerConfig] = {}
        self._clients: Dict[str, _ClientEntry] = {}
        self._exit_stack: Optional[AsyncExitStack] = None
        self._langchain_tools: List[StructuredTool] = []
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # 注册接口（在 lifespan 中调用，连接前配置）
    # ------------------------------------------------------------------

    def register_stdio(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> "MCPToolRegistry":
        """注册一个本地 Stdio MCP Server。"""
        self._configs[name] = StdioServerConfig(
            name=name, command=command, args=args or [], env=env
        )
        return self

    def register_sse(
        self,
        name: str,
        url: str,
        messages_url: Optional[str] = None,
    ) -> "MCPToolRegistry":
        """注册一个远程 SSE MCP Server。"""
        self._configs[name] = SSEServerConfig(
            name=name, url=url, messages_url=messages_url
        )
        return self

    def clear_configs(self) -> None:
        """清理所有已注册的配置，准备重新从后端同步。"""
        self._configs.clear()

    # ------------------------------------------------------------------
    # 生命周期（可安全重复调用）
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """
        同步所有已注册的 MCP Server。
        支持增量更新：已连接的跳过，新增的建立连接，已禁用的断开。
        """
        if self._exit_stack is None:
            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()

        # 1. 断开不再需要的 Server
        current_names = set(self._configs.keys())
        active_names = set(self._clients.keys())
        
        to_remove = active_names - current_names
        for name in to_remove:
            logger.info("🔌 Disconnecting disabled MCP Server: [%s]", name)
            entry = self._clients.pop(name)
            if entry._local_exit_stack:
                await entry._local_exit_stack.aclose()

        # 2. 连接新增或未连接的 Server
        for name, config in self._configs.items():
            if name not in self._clients:
                entry = _ClientEntry(config)
                ok = await entry.connect()
                if ok:
                    self._clients[name] = entry

        # 3. 聚合所有工具并构建 StructuredTool 包装
        await self._rebuild_langchain_tools()
        self._initialized = True
        logger.debug(
            "✅ MCPToolRegistry synced: %d active server(s), %d tool(s) total.",
            len(self._clients),
            len(self._langchain_tools),
        )

    async def teardown(self) -> None:
        """关闭所有连接，在 FastAPI lifespan shutdown 阶段调用。"""
        if self._exit_stack:
            await self._exit_stack.__aexit__(None, None, None)
        self._initialized = False
        logger.info("✅ MCPToolRegistry teardown complete.")

    # ------------------------------------------------------------------
    # 公共查询接口
    # ------------------------------------------------------------------

    async def list_all_tools(self) -> List[Dict[str, Any]]:
        """返回所有已连接 Server 提供的工具 Schema 列表。"""
        result: List[Dict[str, Any]] = []
        for entry in self._clients.values():
            result.extend(await entry.list_tools())
        return result

    def get_langchain_tools(
        self, config: Optional[RunnableConfig] = None
    ) -> List[StructuredTool]:
        """
        返回可直接绑定到 LLM 的 StructuredTool 列表。
        config 用于传递 auth_header 等运行时参数。
        """
        return self._langchain_tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_header: Optional[str] = None,
    ) -> Any:
        """
        按工具名执行 MCP 工具（自动查找所属 Server）。
        """
        for entry in self._clients.values():
            if any(t["name"] == tool_name for t in entry._tools_cache):
                return await entry.call_tool(tool_name, arguments, auth_header)
        return {"error": f"Tool '{tool_name}' not found in any registered MCP server."}

    # ------------------------------------------------------------------
    # 内部构建
    # ------------------------------------------------------------------

    async def _rebuild_langchain_tools(self) -> None:
        """将所有 MCP 工具 Schema 包装为 LangChain StructuredTool。"""
        self._langchain_tools = []
        all_tools = await self.list_all_tools()
        for tool_def in all_tools:
            tool = self._make_structured_tool(tool_def)
            self._langchain_tools.append(tool)

    def _make_structured_tool(self, tool_def: Dict[str, Any]) -> StructuredTool:
        """将单个 MCP 工具定义转换为 StructuredTool。"""
        name = tool_def["name"]
        description = tool_def.get("description", f"Call MCP tool: {name}")
        server_name = tool_def.get("server_name", "")

        # 保存 self 引用，供闭包使用
        registry = self

        async def _wrapper(**kwargs: Any) -> str:
            # 从 kwargs 中提取 config（LangChain 约定的注入方式）
            config: Optional[RunnableConfig] = kwargs.pop("config", None)
            auth_header: Optional[str] = None
            if config:
                auth_header = config.get("configurable", {}).get("auth_header")
            result = await registry.call_tool(name, kwargs, auth_header)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)
            return str(result)

        return StructuredTool.from_function(
            coroutine=_wrapper,
            name=name,
            description=description,
        )


# 全局单例
mcp_tool_registry = MCPToolRegistry()
