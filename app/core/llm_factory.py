import logging
import httpx
import json
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMFactory:
    @staticmethod
    def get_chat_model(provider: str, model_name: str, api_key: str, base_url: str = None):
        if provider == "google":
            return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
        elif provider in ["openai", "new-api"]:
            kwargs = {}
            if settings.LLM_SKIP_SSL_VERIFY:
                kwargs["http_async_client"] = httpx.AsyncClient(verify=False)
            
            return ChatOpenAI(
                model=model_name,
                openai_api_key=api_key,
                base_url=base_url,
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
