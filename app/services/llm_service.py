import logging
import hashlib
import json
from typing import Any, Dict, Optional

from app.core.dynamic_config import dynamic_config
from app.core.llm_factory import LLMFactory

logger = logging.getLogger(__name__)

class LLMService:
    """
    LLM 服务能力类 (Application Service / Infrastructure Adapter)
    
    职责：
    1. 封装 LLM 调用能力，隐藏底层配置获取细节。
    2. 提供单例化的 LLM 实例缓存，避免重复加载配置与初始化。
    3. 感知动态配置变化，自动刷新 LLM 实例。
    """
    
    def __init__(self):
        self._cached_llm = None
        self._last_config_hash = None

    def _get_config_hash(self, config_dict: Dict[str, Any]) -> str:
        """计算配置哈希，用于检测变更。"""
        config_str = json.dumps(config_dict, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def get_default_llm(self, temperature: Optional[float] = None, streaming: bool = True):
        """
        获取当前生效的默认 LLM 实例。
        如果配置未变，则返回缓存实例。
        """
        # 1. 组装当前配置快照
        current_config = {
            "provider": dynamic_config.llm_provider,
            "base_url": dynamic_config.llm_base_url,
            "model": dynamic_config.llm_model,
            "api_key": dynamic_config.llm_api_key,
            "temperature": temperature if temperature is not None else 0.7,
            "streaming": streaming
        }
        
        current_hash = self._get_config_hash(current_config)
        
        # 2. 检查缓存是否有效
        if self._cached_llm and current_hash == self._last_config_hash:
            return self._cached_llm
            
        # 3. 缓存失效，重新创建
        logger.info(f"🔄 LLM Config changed or first load, creating new instance: {current_config['model']} (streaming={streaming})")
        
        llm = LLMFactory.get_llm(
            provider=current_config["provider"],
            base_url=current_config["base_url"],
            model_name=current_config["model"],
            api_key=current_config["api_key"],
            temperature=current_config["temperature"],
            streaming=current_config["streaming"]
        )
        
        self._cached_llm = llm
        self._last_config_hash = current_hash
        
        return llm

# 全局单例
llm_service = LLMService()
