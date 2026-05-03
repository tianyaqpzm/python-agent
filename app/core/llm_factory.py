import logging
from typing import List, Optional
import httpx
import json
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMFactory:
    @staticmethod
    def get_llm(provider: str, model_name: str, api_key: str, base_url: str = None, temperature: float = 0.7):
        if provider == "google":
            return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=temperature, streaming=True)
        elif provider in ["openai", "new-api"]:
            kwargs = {}
            if settings.LLM_SKIP_SSL_VERIFY:
                kwargs["http_async_client"] = httpx.AsyncClient(verify=False)
            
            return ChatOpenAI(
                model=model_name,
                openai_api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                streaming=True,
                **kwargs
            )
        return None

    @staticmethod
    def get_embedding_model(provider: str, model_name: str, api_key: str, base_url: str):
        if provider == "google":
            return GoogleGenerativeAIEmbeddings(model=model_name, google_api_key=api_key)
        
        elif provider.lower() in ["openai", "new-api"]:
            kwargs = {}
            if base_url:
                kwargs["base_url"] = base_url
            
            if settings.LLM_SKIP_SSL_VERIFY:
                kwargs["http_async_client"] = httpx.AsyncClient(verify=False)
                kwargs["http_client"] = httpx.Client(verify=False)

            logger.info(f"🏗️ 正在构建 Embedding 模型: Provider={provider}, Model={model_name}")
            
            return OpenAIEmbeddings(
                model=model_name,
                openai_api_key=api_key,
                **kwargs
            )
        else:
            raise ValueError(f"Unsupported Embedding provider: {provider}")

    @staticmethod
    async def aembed_texts_manual(texts: List[str], model_name: str, api_key: str, base_url: str) -> List[List[float]]:
        """
        手动通过 httpx 调用 Embedding 接口，规避 LangChain 内部参数处理坑。
        支持批量输入。
        """
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_name,
            "input": texts
        }
        
        # 兼容 SSL 校验跳过
        verify = not settings.LLM_SKIP_SSL_VERIFY
        
        async with httpx.AsyncClient(verify=verify) as client:
            resp = await client.post(f"{base_url}/embeddings", json=payload, headers=headers, timeout=60.0)
            if resp.status_code != 200:
                raise RuntimeError(f"Embedding API Error {resp.status_code}: {resp.text}")
            
            data = resp.json()["data"]
            # 按照返回列表提取向量
            return [item["embedding"] for item in data]
