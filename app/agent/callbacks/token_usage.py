import json
import time
import logging
from typing import Any, Dict, List

from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)

class TokenUsageCallbackHandler(AsyncCallbackHandler):
    """
    异步回调处理器，拦截并解析 LLM 的请求时间与 usage_metadata。
    将消耗数据格式化并输出到标准输出，以便 ms-ai-devops 解析。
    """
    def __init__(self, role: str):
        self.role = role
        self.start_time = 0

    async def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        self.start_time = time.time()

    async def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any
    ) -> None:
        self.start_time = time.time()

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        duration_ms = int((time.time() - self.start_time) * 1000)
        input_tokens = 0
        output_tokens = 0
        model_name = "unknown"
        
        # Parse from response.llm_output (often available for OpenAI)
        if response.llm_output:
            model_name = response.llm_output.get("model_name", model_name)
            if "token_usage" in response.llm_output:
                usage = response.llm_output["token_usage"]
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
        
        # Parse from generations
        if response.generations and len(response.generations) > 0 and len(response.generations[0]) > 0:
            msg = response.generations[0][0].message
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                input_tokens = msg.usage_metadata.get("input_tokens", input_tokens)
                output_tokens = msg.usage_metadata.get("output_tokens", output_tokens)
            
            # Additional check for response_metadata in some models
            if hasattr(msg, "response_metadata") and msg.response_metadata:
                model_name = msg.response_metadata.get("model_name", model_name)
                if "token_usage" in msg.response_metadata:
                    tu = msg.response_metadata["token_usage"]
                    input_tokens = tu.get("prompt_tokens", input_tokens)
                    output_tokens = tu.get("completion_tokens", output_tokens)

        # Cost estimation mapping locally or leaving to ms-ai-devops. 
        # ms-ai-devops backend re-computes cost or parses cost if present.
        # We will just pass the basic info.
        
        # Print standard JSON structure to stdout so ms-ai-devops can parse it
        usage_data = {
            "role": self.role,
            "phase": "LLM_CALL",
            "model": model_name,
            "input": input_tokens,
            "output": output_tokens,
            "durationMs": duration_ms
        }
        print(f"__TOKEN_USAGE__:{json.dumps(usage_data)}", flush=True)
