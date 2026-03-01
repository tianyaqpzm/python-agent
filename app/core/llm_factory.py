import logging

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


class LLMFactory:
    @staticmethod
    def get_llm(
        provider: str,
        base_url: str,
        model_name: str,
        api_key: str = "dummy",  # Gateway handles the real key
        temperature: float = 0.7,
    ) -> BaseChatModel:
        """
        Factory to create LLM instances based on provider.
        """
        logger.info(
            f"Initializing LLM: provider={provider}, model={model_name}, base_url={base_url}"
        )

        if provider.lower() == "gemini":
            # For Gemini via Gateway
            # We use transport="rest" to ensure it goes through standard HTTP/s
            # client_options={"api_endpoint": ...} overrides the default Google API host
            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=api_key,  # Library requires a key, even if dummy
                transport="rest",
                client_options={"api_endpoint": base_url},
                temperature=temperature,
                convert_system_message_to_human=True,  # Gemini sometimes needs this
            )

        elif provider.lower() == "openai":
            # For OpenAI (direct or via Gateway)
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
