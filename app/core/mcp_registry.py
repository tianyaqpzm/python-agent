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
        self._exit_stack: Optional[AsyncExitStack] = None

    async def connect(self, exit_stack: AsyncExitStack) -> bool:
        """建立连接并初始化会话。"""
        try:
            if self.config.type == "stdio":
                params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env=self.config.env,
                )
                read, write = await exit_stack.enter_async_context(stdio_client(params))
            else:
                sse_url = self.config.url
                logger.info("📡 Attempting to connect to SSE MCP Server [%s] at %s", self.config.name, sse_url)
                read, write = await exit_stack.enter_async_context(sse_client(sse_url))

            self.session = await exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.session.initialize()
            logger.info("✅ MCP Server [%s] connected and initialized.", self.config.name)
            return True
        except Exception as exc:
            logger.exception("❌ MCP Server [%s] connect failed: %s", self.config.name, exc)
            return False

    async def list_tools(self) -> List[Dict[str, Any]]:
        """获取工具列表（含 Schema），缓存到实例。"""
        if not self.session:
            return []
        try:
            response = await self.session.list_tools()
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
                "🔧 MCP Server [%s] provides %d tool(s): %s",
                self.config.name,
                len(self._tools_cache),
                [t["name"] for t in self._tools_cache],
            )
            return self._tools_cache
        except Exception as exc:
            logger.error("❌ list_tools from [%s] failed: %s", self.config.name, exc)
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_header: Optional[str] = None,
    ) -> Any:
        """调用指定工具，支持 Token 透传（SSE 模式）。"""
        if not self.session:
            return {"error": "Session not connected"}
        try:
            # SSE 模式下的 Token 透传由 httpx headers 处理
            # Stdio 模式暂不支持 Token（本地进程无需鉴权）
            result = await self.session.call_tool(tool_name, arguments)
            if result.content:
                # 尝试提取文本内容
                content_parts = []
                for c in result.content:
                    if hasattr(c, "text"):
                        content_parts.append(c.text)
                return "\n".join(content_parts) if content_parts else str(result.content)
            return ""
        except Exception as exc:
            logger.error("❌ call_tool [%s/%s] failed: %s", self.config.name, tool_name, exc)
            return {"error": str(exc)}


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

    # ------------------------------------------------------------------
    # 生命周期（在 lifespan 中调用）
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """
        连接所有已注册的 MCP Server，并缓存工具列表。
        在 FastAPI lifespan startup 阶段调用。
        """
        if not self._configs:
            logger.warning("⚠️  MCPToolRegistry: no servers registered, skipping setup.")
            return

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for name, config in self._configs.items():
            entry = _ClientEntry(config)
            ok = await entry.connect(self._exit_stack)
            if ok:
                self._clients[name] = entry

        # 聚合所有工具并构建 StructuredTool 包装
        await self._rebuild_langchain_tools()
        self._initialized = True
        logger.info(
            "✅ MCPToolRegistry ready: %d server(s), %d tool(s) total.",
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
