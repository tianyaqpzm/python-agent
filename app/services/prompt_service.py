import httpx
import logging
import random
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.core.config import settings
from app.core.nacos import nacos_manager

logger = logging.getLogger(__name__)

class PromptService:
    def __init__(self):
        self.java_service_name = settings.NACOS_JAVA_SERVICE_NAME
        # 增加内存缓存，避免频繁网络请求
        # 格式: { slug: {"content": str, "timestamp": float} }
        self._prompt_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 600  # 缓存 600 秒

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
        # 1. 检查缓存
        now = datetime.now().timestamp()
        if slug in self._prompt_cache:
            cache_data = self._prompt_cache[slug]
            if now - cache_data["timestamp"] < self._cache_ttl:
                logger.debug(f"🎯 Cache hit for prompt: {slug}")
                return cache_data["content"]

        # 2. 发现服务地址
        base_url = await self._get_java_base_url()
        if not base_url:
            return None

        url = f"{base_url}/rest/biz/v1/prompts/{slug}"
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 增加超时时间到 15s，并添加重试逻辑
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        # 3. 更新缓存
                        self._prompt_cache[slug] = {
                            "content": data,
                            "timestamp": now
                        }
                        return data
                    else:
                        logger.error(f"Failed to fetch prompt {slug}: {response.status_code} - {response.text}")
                        return None
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⏳ Attempt {attempt + 1} failed for prompt {slug} due to timeout, retrying...")
                    continue
                logger.error(f"❌ Final attempt failed for prompt {slug}: {e}")
                return None
            except Exception as e:
                logger.exception(f"❌ Unexpected error calling prompt service (slug={slug}): {e}")
                return None

    def render_prompt(self, template: str, variables: Dict[str, Any]) -> str:
        """
        渲染 Prompt 占位符 {{variable}}。
        
        支持系统级自动注入变量：
        - current_time: 当前时间 (YYYY-MM-DD HH:mm:ss)
        - today: 今天日期 (YYYY-MM-DD)
        """
        # 1. 准备基础变量
        now = datetime.now()
        all_vars = {
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "today": now.strftime("%Y-%m-%d"),
        }
        
        # 2. 合并传入变量（允许覆盖系统变量）
        if variables:
            all_vars.update(variables)

        # 3. 执行替换
        rendered = template
        for key, value in all_vars.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in rendered:
                rendered = rendered.replace(placeholder, str(value))
        
        return rendered

    async def get_rendered_prompt(
        self, 
        slug: str, 
        variables: Dict[str, Any], 
        headers: Optional[Dict[str, str]] = None,
        fallback: Optional[str] = None
    ) -> str:
        """
        组合操作：获取 Prompt 并渲染。
        如果获取失败，且提供了 fallback，则渲染 fallback 模板。
        """
        prompt_data = await self.get_active_prompt(slug, headers=headers)
        template = None
        
        if prompt_data and prompt_data.get("content"):
            template = prompt_data["content"]
        elif fallback:
            template = fallback
            
        if template:
            return self.render_prompt(template, variables)
        
        return ""

# Singleton
prompt_service = PromptService()
