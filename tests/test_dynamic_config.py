import pytest
from unittest.mock import MagicMock, patch
from app.core.dynamic_config import DynamicConfig
from app.core.config import settings

def test_dynamic_config_fallback_to_settings():
    """测试 DynamicConfig 的属性兜底逻辑"""
    config = DynamicConfig()
    # 假设 settings 有 LLM_RPM = 60
    # 验证 llm_rpm 不在实例的 __dict__ 中（即没有被直接设置）
    assert "llm_rpm" not in config.__dict__
    
    # 触发 __getattr__
    val = config.llm_rpm
    assert val == settings.LLM_RPM

def test_dynamic_config_nacos_load_success():
    """测试 Nacos 配置加载后的属性同步"""
    config = DynamicConfig()
    
    # 模拟 Nacos 返回内容
    mock_yaml = "LLM_RPM: 100\nPG_HOST: 'nacos-host'"
    
    with patch("app.core.nacos.nacos_manager.get_config", return_value=mock_yaml), \
         patch("app.core.nacos.nacos_manager.add_config_watcher"):
        config.watch_config()
        
        # 验证属性已被注入实例
        assert config.llm_rpm == 100
        # 验证 settings 也被更新
        assert settings.LLM_RPM == 100

def test_dynamic_config_nacos_load_failure_fallback():
    """测试 Nacos 加载失败后的全量同步兜底"""
    config = DynamicConfig()
    
    with patch("app.core.nacos.nacos_manager.get_config", return_value=None), \
         patch("app.core.nacos.nacos_manager.add_config_watcher"):
        config.watch_config()
        
        # 应该执行了 _sync_from_settings
        # 验证常见属性是否存在
        assert hasattr(config, "service_name")
        assert config.service_name == settings.SERVICE_NAME

