import httpx
import logging
import random
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.nacos import nacos_manager

logger = logging.getLogger(__name__)

class PromptService:
    def __init__(self):
        self.java_service_name = settings.NACOS_JAVA_SERVICE_NAME

    async def _get_java_base_url(self) -> Optional[str]:
        """通过 Nacos 发现 ms-java-biz 的地址"""
        instances = nacos_manager.get_service(self.java_service_name)
        if not instances:
            logger.error(f"No healthy instances found for {self.java_service_name}")
            return None
        
        # 简单负载均衡：随机选择一个实例
        instance = random.choice(instances)
        return f"http://{instance['ip']}:{instance['port']}"

    async def get_active_prompt(self, slug: str, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """从 ms-java-biz 获取生效状态的 Prompt 模板与版本配置"""
        base_url = await self._get_java_base_url()
        if not base_url:
            return None

        url = f"{base_url}/rest/biz/v1/prompts/{slug}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to fetch prompt {slug}: {response.status_code} - {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Error calling prompt service: {e}")
            return None

    def render_prompt(self, template: str, variables: Dict[str, Any]) -> str:
        """渲染 Prompt 占位符 {{variable}}"""
        rendered = template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            rendered = rendered.replace(placeholder, str(value))
        return rendered

# Singleton
prompt_service = PromptService()
