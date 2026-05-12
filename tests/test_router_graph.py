"""
路由架构验收测试

验收标准：
- PR-01: 输入"帮我查一下X文档" → Router 100% 路由到 RAG 子图
- PR-02: 输入"帮我写一段Python" → Router 100% 路由到 Coding 子图
- PR-03: 通用输入 → 路由到 General 子图
- PR-04: Router Graph 包含正确的节点结构
- PR-05: MCPToolRegistry 单例可正常注册配置

测试策略：
- 路由测试直接调用 router_node（不启动 LLM，验证关键词规则）
- 图结构测试验证节点存在性
- MCP Registry 测试验证注册逻辑（不建立真实连接）
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


class TestRouterNodeKeywords:
    """PR-01 ~ PR-03: router_node 关键词路由验收测试"""

    @pytest.mark.asyncio
    async def test_rag_routing_with_document_query(self):
        """PR-01: 含'查文档'关键词 → intent == 'rag'"""
        from app.agent.router.node import router_node

        state = {
            "messages": [HumanMessage(content="帮我查一下X文档")],
            "intent": None,
            "topic_id": None,
            "auth_header": None,
            "sources": [],
        }
        config = {"configurable": {}}
        result = await router_node(state, config)
        assert result["intent"] == "rag", (
            f"Expected intent='rag', got '{result['intent']}' for '帮我查一下X文档'"
        )

    @pytest.mark.asyncio
    async def test_coding_routing_with_python_request(self):
        """PR-02: 含'写一段Python'关键词 → intent == 'coding'"""
        from app.agent.router.node import router_node

        state = {
            "messages": [HumanMessage(content="帮我写一段Python代码")],
            "intent": None,
            "topic_id": None,
            "auth_header": None,
            "sources": [],
        }
        config = {"configurable": {}}
        result = await router_node(state, config)
        assert result["intent"] == "coding", (
            f"Expected intent='coding', got '{result['intent']}' for '帮我写一段Python代码'"
        )

    @pytest.mark.asyncio
    async def test_rag_routing_variants(self):
        """PR-01 变体：多种 RAG 意图表达均能正确路由"""
        from app.agent.router.node import router_node

        rag_queries = [
            "帮我查一下X文档",
            "搜一下这个话题的资料",         # 不含 Python 关键词
            "找找知识库里有没有这个",
            "这个词是什么意思？",
            "介绍一下LangGraph",
        ]
        config = {"configurable": {}}
        for query in rag_queries:
            state = {
                "messages": [HumanMessage(content=query)],
                "intent": None,
                "topic_id": None,
                "auth_header": None,
                "sources": [],
            }
            result = await router_node(state, config)
            assert result["intent"] == "rag", (
                f"Expected intent='rag', got '{result['intent']}' for '{query}'"
            )

    @pytest.mark.asyncio
    async def test_coding_routing_variants(self):
        """PR-02 变体：多种 Coding 意图表达均能正确路由"""
        from app.agent.router.node import router_node

        coding_queries = [
            "帮我写一段Python",
            "用Java实现一个排序算法",
            "帮我debug这段代码",
            "写一个TypeScript函数",
            "帮我实现二分搜索",
        ]
        config = {"configurable": {}}
        for query in coding_queries:
            state = {
                "messages": [HumanMessage(content=query)],
                "intent": None,
                "topic_id": None,
                "auth_header": None,
                "sources": [],
            }
            result = await router_node(state, config)
            assert result["intent"] == "coding", (
                f"Expected intent='coding', got '{result['intent']}' for '{query}'"
            )

    @pytest.mark.asyncio
    async def test_general_routing_for_unrecognized_queries(self):
        """PR-03: LLM 分类失败时 fallback 到 general"""
        from app.agent.router.node import router_node

        # Patch LLM，让它返回 general
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="general"))

        with patch("app.agent.router.node.LLMFactory.get_llm", return_value=mock_llm):
            state = {
                "messages": [HumanMessage(content="今天天气怎么样")],
                "intent": None,
                "topic_id": None,
                "auth_header": None,
                "sources": [],
            }
            config = {"configurable": {}}
            result = await router_node(state, config)
            assert result["intent"] == "general"

    @pytest.mark.asyncio
    async def test_empty_messages_defaults_to_general(self):
        """PR-03: 空消息列表 → general"""
        from app.agent.router.node import router_node

        state = {
            "messages": [],
            "intent": None,
            "topic_id": None,
            "auth_header": None,
            "sources": [],
        }
        config = {"configurable": {}}
        result = await router_node(state, config)
        assert result["intent"] == "general"


class TestRouterGraphStructure:
    """PR-04: Global Router Graph 节点结构验证"""

    def test_router_graph_has_required_nodes(self):
        """路由图必须包含 router + 三个子图节点"""
        from app.agent.router.graph import build_router_graph

        builder = build_router_graph()
        node_names = set(builder.nodes.keys())
        assert "router" in node_names, "Router graph must have 'router' node"
        assert "rag_subgraph" in node_names, "Router graph must have 'rag_subgraph' node"
        assert "coding_subgraph" in node_names, "Router graph must have 'coding_subgraph' node"
        assert "general_subgraph" in node_names, "Router graph must have 'general_subgraph' node"
        # 模式 B：A2A 远端节点
        assert "remote_agent_subgraph" in node_names, "Router graph must have 'remote_agent_subgraph' node"

    def test_router_graph_compiles_without_error(self):
        """路由图可以编译为可执行图（不含 checkpointer）"""
        from app.agent.router.graph import build_router_graph

        builder = build_router_graph()
        compiled = builder.compile()
        assert compiled is not None


class TestMCPRegistryUnit:
    """PR-05: MCPToolRegistry 单元测试（不建立真实连接）"""

    def test_registry_register_stdio(self):
        """注册 Stdio Server 配置后，config 字典中存在该配置"""
        from app.core.mcp_registry import MCPToolRegistry

        registry = MCPToolRegistry()
        registry.register_stdio(name="test-fs", command="npx", args=["-y", "@mcp/server-fs"])
        assert "test-fs" in registry._configs
        assert registry._configs["test-fs"].type == "stdio"

    def test_registry_register_sse(self):
        """注册 SSE Server 配置后，config 字典中存在该配置"""
        from app.core.mcp_registry import MCPToolRegistry

        registry = MCPToolRegistry()
        registry.register_sse(name="java-biz", url="http://localhost:8080/mcp/sse")
        assert "java-biz" in registry._configs
        assert registry._configs["java-biz"].type == "sse"

    def test_registry_singleton_is_consistent(self):
        """全局单例在多次 import 时是同一个对象"""
        from app.core.mcp_registry import mcp_tool_registry as r1
        from app.core.mcp_registry import mcp_tool_registry as r2
        assert r1 is r2

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_when_not_found(self):
        """工具未注册时，call_tool 返回 error 信息而非异常"""
        from app.core.mcp_registry import MCPToolRegistry

        registry = MCPToolRegistry()
        result = await registry.call_tool("nonexistent_tool", {})
        assert "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_list_all_tools_returns_empty_when_no_clients(self):
        """无已连接客户端时，list_all_tools 返回空列表"""
        from app.core.mcp_registry import MCPToolRegistry

        registry = MCPToolRegistry()
        tools = await registry.list_all_tools()
        assert tools == []


class TestSubgraphStructure:
    """子图节点结构验证"""

    def test_rag_subgraph_has_required_nodes(self):
        """RAG 子图包含 rag_agent + tools 节点"""
        from app.agent.subgraphs.rag_graph import build_rag_subgraph

        builder = build_rag_subgraph()
        assert "rag_agent" in builder.nodes
        assert "tools" in builder.nodes

    def test_coding_subgraph_compiles(self):
        """Coding 子图可以编译"""
        from app.agent.subgraphs.coding_graph import build_coding_subgraph

        builder = build_coding_subgraph()
        compiled = builder.compile()
        assert compiled is not None

    def test_general_subgraph_compiles(self):
        """General 子图可以编译"""
        from app.agent.subgraphs.general_graph import build_general_subgraph

        builder = build_general_subgraph()
        compiled = builder.compile()
        assert compiled is not None


class TestA2ARemoteAgent:
    """模式 B：A2A 远端 Agent 验收测试"""

    @pytest.mark.asyncio
    async def test_remote_agent_routing_by_keyword(self):
        """含「委托」关键词 → intent == 'remote_agent'"""
        from app.agent.router.node import router_node

        state = {
            "messages": [HumanMessage(content="请委托外部agent处理这个请求")],
            "intent": None,
            "topic_id": None,
            "auth_header": None,
            "sources": [],
            "handled_by": None,
            "a2a_task_id": None,
            "artifacts": [],
            "handoff_context": None,
        }
        config = {"configurable": {}}
        result = await router_node(state, config)
        assert result["intent"] == "remote_agent", (
            f"Expected intent='remote_agent', got '{result['intent']}'"
        )

    def test_remote_agent_subgraph_compiles(self):
        """A2A 子图可以编译（骨架完整）"""
        from app.agent.subgraphs.remote_agent_graph import build_remote_agent_subgraph

        builder = build_remote_agent_subgraph()
        compiled = builder.compile()
        assert compiled is not None

    def test_remote_agent_subgraph_has_remote_agent_node(self):
        """A2A 子图包含 remote_agent 节点"""
        from app.agent.subgraphs.remote_agent_graph import build_remote_agent_subgraph

        builder = build_remote_agent_subgraph()
        assert "remote_agent" in builder.nodes

    @pytest.mark.asyncio
    async def test_remote_agent_node_returns_placeholder_when_nacos_unavailable(self):
        """当 Nacos 不可达时，A2A 节点返回错误提示而非抛出异常"""
        from app.agent.subgraphs.remote_agent_graph import remote_agent_node
        from unittest.mock import patch, AsyncMock

        state = {
            "messages": [HumanMessage(content="委托外部处理")],
            "intent": "remote_agent",
            "topic_id": None,
            "auth_header": None,
            "sources": [],
            "handled_by": None,
            "a2a_task_id": None,
            "artifacts": [],
            "handoff_context": None,
            "remote_agent_name": None,
            "remote_agent_url": None,
        }
        config = {"configurable": {"thread_id": "test-thread"}}

        # Mock Nacos 返回空实例列表（模拟服务不可达）
        with patch(
            "app.agent.subgraphs.remote_agent_graph._resolve_agent_url",
            new=AsyncMock(return_value=None),
        ):
            result = await remote_agent_node(state, config)

        # 应返回错误提示而非抛异常
        assert result["messages"] is not None
        assert len(result["messages"]) == 1
        assert result["a2a_task_id"] is None
        assert result["artifacts"] == []
        assert "unavailable" in result["handled_by"]

    def test_global_state_has_a2a_fields(self):
        """GlobalState 包含所有 A2A 扩展字段"""
        from app.agent.state import GlobalState
        import typing
        hints = typing.get_type_hints(GlobalState)
        for field in ("handled_by", "a2a_task_id", "artifacts", "handoff_context"):
            assert field in hints, f"GlobalState missing A2A field: '{field}'"
