"""
路由节点（Router Node）

职责：
- 接收用户消息，调用 LLM 进行意图分类
- 将分类结果写入 state["intent"]（"rag" / "coding" / "general"）

设计决策：
- 业务优先级（最高）：若 state 中存在 topic_id，则强制判定为 "rag" 意图（意味着用户已进入特定知识库话题）
- 规则优先级：优先使用关键词规则匹配（确保测试可预测性，100% 覆盖率）
- 智能兜底：关键词未匹配时 fallback 到 LLM 分类
- LLM 分类的 System Prompt 从 ms-java-biz Prompt 接口动态获取
  slug: router_intent_classifier，拉取失败时降级到内置 Fallback 模版
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig

from app.agent.state import GlobalState, IntentType
from app.core.dynamic_config import dynamic_config
from app.services.llm_service import llm_service
from app.services.prompt_service import prompt_service

logger = logging.getLogger(__name__)

# ── 关键词规则表（优先于 LLM 分类，保证测试确定性）────────────────────────
# A2A 远端委托（最高优先级，明确指向外部 Agent）
_REMOTE_AGENT_KEYWORDS = re.compile(
    r"委托|转交|外部agent|远端|外部服务",
    re.IGNORECASE,
)
# Coding 关键词（优先于 RAG，避免“查bug”被错分为 rag）
_CODING_KEYWORDS = re.compile(
    r"写.*代码|代码|编程|python|java|javascript|typescript|函数|算法|实现|debug|bug|程序",
    re.IGNORECASE,
)
# RAG 检索
_RAG_KEYWORDS = re.compile(
    r"查|搜|找|文档|知识库|资料|记录|查询|检索|介绍|说明|是什么|什么是",
    re.IGNORECASE,
)

# ── 内置 Fallback Prompt（ms-java-biz 不可达时使用）────────────────────────
# 在 ms-java-biz 中预置 slug=router_intent_classifier 的 Prompt 可覆盖此内容。
_FALLBACK_ROUTER_PROMPT = """你是一个意图路由器，请根据用户的消息，将其分类为以下三类之一，只输出类别名称，不要有任何解释：
- rag: 用户想要查询文档、知识库、资料、记录，或者询问某个领域的知识
- coding: 用户想要编写代码、调试代码、解决编程问题
- general: 其他通用问题或对话

只输出 rag、coding 或 general 三个单词之一。"""

# ms-java-biz 中对应的 Prompt slug
_ROUTER_PROMPT_SLUG = "router_intent_classifier"


async def _get_router_prompt(auth_header: Optional[str] = None) -> str:
    """
    从 ms-java-biz Prompt 服务动态获取意图分类 System Prompt，并执行变量替换。
    """
    headers = {"Authorization": auth_header} if auth_header else {}
    variables = {
        "intent_list": "rag, coding, general, remote_agent"
    }
    return await prompt_service.get_rendered_prompt(
        _ROUTER_PROMPT_SLUG,
        variables=variables,
        headers=headers,
        fallback=_FALLBACK_ROUTER_PROMPT
    )


def _keyword_classify(text: str) -> Optional[IntentType]:
    """
    基于关键词的快速分类（规则优先，确保测试可预测性）。
    返回意图标签，未匹配时返回 None（交由 LLM 分类）。

    优先级（高 → 低）：
    1. remote_agent：明确指向外部 Agent——最确定的意图
    2. coding：编程意图（优先于 RAG，避免“查bug”被错分）
    3. rag：检索意图
    4. 未命中 → None
    """
    if _REMOTE_AGENT_KEYWORDS.search(text):
        return "remote_agent"
    if _CODING_KEYWORDS.search(text):
        return "coding"
    if _RAG_KEYWORDS.search(text):
        return "rag"
    return None


async def router_node(state: GlobalState, config: RunnableConfig) -> Dict[str, Any]:
    """
    意图路由节点。

    执行流程：
    1. 提取最后一条人类消息
    2. 尝试关键词规则匹配
    3. 规则未命中时调用 LLM 分类
    4. 将 intent 写回 state
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "general"}

    # 提取最后一条用户消息文本
    human_messages = [m for m in messages if isinstance(m, HumanMessage)]
    user_text: str = ""
    if human_messages:
        last = human_messages[-1]
        if isinstance(last.content, str):
            user_text = last.content
        elif isinstance(last.content, list):
            # 处理多模态消息
            user_text = " ".join(
                p.get("text", "") for p in last.content
                if isinstance(p, dict) and p.get("type") == "text"
            ).strip()

    if not user_text:
        return {"intent": "general"}

    # ── 强制性业务逻辑：如果携带 topic_id，则必须走 RAG 流程 ───────────────────
    # 注意：topic_id 可能在 state 中，也可能在 config.configurable 中
    topic_id = state.get("topic_id") or config.get("configurable", {}).get("topic_id")
    
    if topic_id:
        logger.info("🗺️  Router [force] → intent=rag (topic_id detected: %s)", topic_id)
        return {"intent": "rag", "topic_id": topic_id}

    # 优先使用关键词规则
    intent = _keyword_classify(user_text)
    if intent:
        logger.info("🗺️  Router [keyword] → intent=%s | text='%s'", intent, user_text[:50])
        return {"intent": intent}

    # Fallback：从 ms-java-biz 获取动态 Prompt，调用 LLM 分类
    try:
        auth_header = state.get("auth_header") or config.get("configurable", {}).get("auth_header")
        system_prompt = await _get_router_prompt(auth_header=auth_header)

        llm = llm_service.get_default_llm(temperature=0.1, streaming=False)
        from app.agent.callbacks.token_usage import TokenUsageCallbackHandler
        cb = TokenUsageCallbackHandler("ROUTER")
        
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_text),
            ],
            config={"callbacks": [cb]}
        )
        raw = response.content.strip().lower()
        intent = raw if raw in ("rag", "coding", "general", "remote_agent") else "general"
        logger.info("🗺️  Router [llm] → intent=%s | text='%s'", intent, user_text[:50])
    except Exception as exc:
        logger.error("❌ Router LLM classification failed: %s. Fallback to general.", exc)
        intent = "general"

    return {"intent": intent}
