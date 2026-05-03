import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncGenerator
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from app.core.config import settings
from app.core.llm_factory import LLMFactory
from app.core.limiter import LimiterRegistry

logger = logging.getLogger(__name__)


class BaseGenerationProcessor(ABC):
    """
    大脑生成处理器的抽象基类，使用**模板方法模式** (Template Method Pattern)。
    封装了解答大语言模型的全生命周期控制流。
    """
    def __init__(self):
        self.model_name = settings.KB_LLM_MODEL
        self.llm = LLMFactory.get_llm(
            provider=settings.KB_LLM_PROVIDER,
            model_name=self.model_name,
            base_url=settings.KB_BASE_URL,
            api_key=settings.KB_API_KEY,
            temperature=settings.KB_LLM_TEMPERATURE
        )

    async def process_answer(self, query: str, context_docs: List[Dict[str, Any]]) -> str:
        """非流式模板主方法"""
        logger.info(f"[{self.__class__.__name__}] 6.开始执行脑力生成总线...")
        
        real_query = await self._rewrite_query(query)
        intent = await self._route_intent(real_query)
        
        logger.info(f"[{self.__class__.__name__}] 问题重构为 [{real_query}], 路由意图 [{intent}]")
        return await self._generate_answer(real_query, context_docs, intent)

    async def process_answer_stream(self, query: str, context_docs: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        """流式模板主方法"""
        logger.info(f"[{self.__class__.__name__}] 6.开始执行脑力生成总线 (Stream)...")
        real_query = await self._rewrite_query(query)
        intent = await self._route_intent(real_query)
        
        async for chunk in self._generate_answer_stream(real_query, context_docs, intent):
            yield chunk

    async def _rewrite_query(self, query: str) -> str:
        """【可选覆盖】意图扩展及重写增强。默认原封不动"""
        return query

    async def _route_intent(self, query: str) -> str:
        """【可选覆盖】意图发牌器，默认全部归类为 general 普世意图"""
        return "general"

    def _build_context(self, docs: List[Dict[str, Any]], max_length: int = 3000) -> str:
        """默认将提供的所有 Chunks 上下文拼成供基座服用的 String，并实施长度熔断"""
        if not docs:
            return "暂无相关参考资料信息。"

        context_parts = []
        current_length = 0

        for i, doc in enumerate(docs, 1):
            content = doc.get("content", "")
            meta = doc.get("metadata", {})
            source = meta.get("source_file", "未知")

            # 构建文档文本
            doc_text = f"【参考资料 {i}】来源 [{source}]\n{content}\n"
            
            if current_length + len(doc_text) > max_length:
                break
            
            context_parts.append(doc_text)
            current_length += len(doc_text)

        return "\n" + "=" * 50 + "\n".join(context_parts)

    @abstractmethod
    async def _generate_answer(self, query: str, docs: List[Dict[str, Any]], intent: str) -> str:
        pass

    @abstractmethod
    async def _generate_answer_stream(self, query: str, docs: List[Dict[str, Any]], intent: str) -> AsyncGenerator[str, None]:
        pass


class DefaultGenerationProcessor(BaseGenerationProcessor):
    """通用知识库领域的回答生成脑力"""
    async def _generate_answer(self, query: str, docs: List[Dict[str, Any]], intent: str) -> str:
        context_text = self._build_context(docs)
        if not docs:
            return "抱歉，知识库中未能找到与您问题直接相关的内容。"

        prompt = ChatPromptTemplate.from_template(
            "你是一个专业的企业知识库问答助手。请仅根据下列提供的参考资料来回答问题。\n"
            "如果无法找到答案，请诚实说明，不要编造。\n\n"
            "参考资料:\n{context}\n\n"
            "用户问题: {question}"
        )
        chain = {"question": RunnablePassthrough(), "context": lambda _: context_text} | prompt | self.llm | StrOutputParser()
        
        limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
        async with limiter:
            return await chain.ainvoke(query)

    async def _generate_answer_stream(self, query: str, docs: List[Dict[str, Any]], intent: str) -> AsyncGenerator[str, None]:
        context_text = self._build_context(docs)
        if not docs:
            yield "抱歉，知识库中未能找到与您问题直接相关的内容。"
            return

        prompt = ChatPromptTemplate.from_template(
            "你是一个专业的知识库问答助手。请仅根据下列提供的参考资料来回答问题。\n"
            "参考资料:\n{context}\n\n问题: {question}"
        )
        chain = {"question": RunnablePassthrough(), "context": lambda _: context_text} | prompt | self.llm | StrOutputParser()
        limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
        async with limiter:
            async for chunk in chain.astream(query):
                yield chunk


class HowToCookGenerationProcessor(BaseGenerationProcessor):
    """
    专注于饮食烹饪垂直知识的大脑。拥有强大的提问模糊泛化和特定的 LCEL 回复模板（Emoji+规范排版）。
    """
    async def _rewrite_query(self, query: str) -> str:
        # 拦截过短或模糊的问题进行补全预测
        prompt = ChatPromptTemplate.from_template(
            "你是一个智能查询分析助手。判断用户查询是否需要重写来提高食谱搜索效率。\n"
            "规则：如果包含明确菜名(红烧肉)或具体询问(如何倒酱油)则原样返回。\n"
            "如果模糊(有什么好吃的/晚餐吃什么/推荐肉菜)，将其替换成'简单易做菜谱推荐'或者具体增加相关烹饪术语。\n"
            "原始查询: {query}\n\n"
            "只输出你重写后的最终查询字符串(无视引号等啰嗦前缀):"
        )
        chain = {"query": RunnablePassthrough()} | prompt | self.llm | StrOutputParser()
        try:
            limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
            async with limiter:
                res = await chain.ainvoke(query)
            return res.strip()
        except Exception as e:
            logger.warning(f"Failed to rewrite query: {e}")
            return query

    async def _route_intent(self, query: str) -> str:
        prompt = ChatPromptTemplate.from_template(
            "根据用户问题分类为下面三种类型:\n"
            "1. 'list' - 推荐类，列举推荐列表 (如:推荐几个素食可以吗)\n"
            "2. 'detail' - 详解类，细致步骤 (如:肉末茄子怎么做/宫保鸡丁料酒放多少)\n"
            "3. 'general' - 一般问题\n"
            "用户问题: {query}\n"
            "输出结果 (只填 list 或 detail 或 general):"
        )
        chain = {"query": RunnablePassthrough()} | prompt | self.llm | StrOutputParser()
        try:
            limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
            async with limiter:
                res = (await chain.ainvoke(query)).strip().lower()
            return res if res in ['list', 'detail', 'general'] else 'general'
        except Exception as e:
            logger.warning(f"Failed to route intent: {e}")
            return 'general'

    def _get_prompt_by_intent(self, intent: str, context: str, query: str) -> ChatPromptTemplate:
        if intent == "list":
            return ChatPromptTemplate.from_template(
                "你是一个主厨。用户的需求是对菜品列举。请看看下文资料提到的所有菜品名称并进行规整打分推荐。\n"
                "参考资料: {context}\n\n"
                "问题: {question}\n\n"
                "请用无序列表回答，无需过于复杂的讲解。"
            )
        elif intent == "detail":
            return ChatPromptTemplate.from_template(
                "你是一位专业的星级烹饪导师。请根据食谱信息提供详细的**分步骤**指导。\n"
                "参考资料: {context}\n\n"
                "问题: {question}\n\n"
                "回答要求强制按下面带 Emoji 的结构作答（没有提到的部分可以省略）：\n"
                "## 🥘 菜品介绍\n"
                "## 🛒 准备食材\n"
                "## 👨‍🍳 制作步骤\n"
                "## 💡 导师技巧提醒"
            )
        else:
            return ChatPromptTemplate.from_template(
                "你是一位厨艺交流博主。请根据食谱资料回答。如果不懂，请老实交代。\n"
                "参考资料: {context}\n\n问题: {question}"
            )

    async def _generate_answer(self, query: str, docs: List[Dict[str, Any]], intent: str) -> str:
        if not docs: return "抱歉，目前我们的厨艺库还没找到这道菜哦。"
        context_text = self._build_context(docs)
        prompt = self._get_prompt_by_intent(intent, context_text, query)
        chain = {"question": RunnablePassthrough(), "context": lambda _: context_text} | prompt | self.llm | StrOutputParser()
        limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
        async with limiter:
            return await chain.ainvoke(query)

    async def _generate_answer_stream(self, query: str, docs: List[Dict[str, Any]], intent: str) -> AsyncGenerator[str, None]:
        if not docs:
            yield "抱歉，目前我们的厨艺库还没找到相关的解法哦。"
            return
        context_text = self._build_context(docs)
        prompt = self._get_prompt_by_intent(intent, context_text, query)
        chain = {"question": RunnablePassthrough(), "context": lambda _: context_text} | prompt | self.llm | StrOutputParser()
        
        limiter = await LimiterRegistry.get_limiter(f"chat:{self.model_name}", settings.LLM_RPM)
        async with limiter:
            async for chunk in chain.astream(query):
                yield chunk


class GenerationService:
    """
    大脑门面模式及策略路由类，统管流式/非流式的问答大口。
    """
    async def generate_answer(self, query: str, context_docs: List[Dict[str, Any]], category: str = "default") -> str:
        if category and category.lower() in ["howtocook", "recipe"]:
            processor = HowToCookGenerationProcessor()
        else:
            processor = DefaultGenerationProcessor()
        return await processor.process_answer(query, context_docs)
        
    async def generate_answer_stream(self, query: str, context_docs: List[Dict[str, Any]], category: str = "default") -> AsyncGenerator[str, None]:
        if category and category.lower() in ["howtocook", "recipe"]:
            processor = HowToCookGenerationProcessor()
        else:
            processor = DefaultGenerationProcessor()
            
        async for chunk in processor.process_answer_stream(query, context_docs):
            yield chunk
