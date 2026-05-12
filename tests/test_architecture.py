"""
架构守护测试：TypedDict 字段、继承体系、Config 默认值
"""
import pytest
from typing import get_type_hints


class TestArchitectureGuard:
    """PA-01 ~ PA-04: 架构约束验证"""

    # PA-01: AgentState TypedDict 字段完整
    def test_agent_state_fields(self):
        from app.agent.state import AgentState
        hints = get_type_hints(AgentState)
        assert "messages" in hints
        assert "intent" in hints
        assert "topic_id" in hints
        assert "auth_header" in hints
        assert "sources" in hints
        assert "handled_by" in hints
        assert "artifacts" in hints
        assert "handoff_context" in hints
        assert "a2a_task_id" in hints

    # PA-02: ChatState TypedDict 字段验证
    def test_chat_state_fields(self):
        from app.services.chat_graph import ChatState
        hints = get_type_hints(ChatState)
        assert "messages" in hints

    # PA-03: Config 类所有必需属性有默认值
    def test_config_has_defaults(self):
        from app.core.config import Config
        config = Config()
        assert config.HOST is not None
        assert config.PORT is not None
        assert config.JWT_SECRET is not None
        assert config.SERVICE_NAME == "ms-py-agent"
        assert config.NACOS_GROUP == "DEFAULT_GROUP"
        assert isinstance(config.JWT_WHITELIST, list)
        assert len(config.JWT_WHITELIST) > 0

    # PA-04: MCP Client 继承体系
    def test_mcp_client_hierarchy(self):
        from app.services.mcp_client import MCPClient, SSEMCPClient, NacosSSEMCPClient

        assert issubclass(SSEMCPClient, MCPClient)
        assert issubclass(NacosSSEMCPClient, SSEMCPClient)

        # 验证基类方法存在
        assert hasattr(MCPClient, "list_tools")
        assert hasattr(MCPClient, "call_tool")
