import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_postgres import PGVector
from app.core.config import settings
from app.core.llm_factory import LLMFactory
from app.core.database import get_engine
from app.core.limiter import LimiterRegistry

logger = logging.getLogger(__name__)


class BaseRetrievalProcessor(ABC):
    """
    检索优化器的抽象基类，使用**模板方法模式** (Template Method Pattern)。
    定义了知识库近似度及混合倒排查询检索的核心生命周期。
    """

    def __init__(self, top_k: int):
        self.top_k = top_k
        self.embeddings = LLMFactory.get_embedding_model(
            provider=settings.KB_EMBEDDING_PROVIDER,
            model_name=settings.KB_EMBEDDING_MODEL,
            base_url=settings.KB_BASE_URL,
            api_key=settings.KB_API_KEY
        )

    async def search(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        模板方法：规定文档搜索逻辑的核心路由。
        """
        logger.info(f"[{self.__class__.__name__}] 5.执行查询检索, Keyword: [{query}], Filters: {filters}")
        if not query or not str(query).strip():
            logger.warning(f"[{self.__class__.__name__}] 收到空查询，跳过检索。")
            return []
        
        query = str(query).strip()
            
        # 1. 执行向量预搜索 / 近似召回 (Vector Retrieval)
        vector_candidates = await self._vector_search(query, filters)
        
        # 2. 执行混合关键词抽取或其他高阶 Rerank 降权逻辑 (Hook)
        final_docs = await self._rerank_results(query, vector_candidates)
        
        # 3. 截断及序列化解析封装
        return self._format_results(final_docs[:self.top_k])

    @abstractmethod
    async def _vector_search(self, query: str, filters: Dict[str, Any]) -> List[Document]:
        """【强制实现】调用底层向量库实现基础的欧式/余弦相似度抽取"""
        pass

    async def _rerank_results(self, query: str, docs: List[Document]) -> List[Document]:
        """【可选覆盖】钩子方法：默认不进行降权排序及混合搜索拓展"""
        return docs

    def _format_results(self, docs: List[Document]) -> List[Dict[str, Any]]:
        """将文档格式化为面向下方的 JSONB"""
        # 注意: 传统 similarity_search 返回的并不携带 score
        # 后续子类可以在 _rerank_results 中打上 'final_score' 
        parsed = []
        for doc in docs:
            score = doc.metadata.get('rrf_score') or doc.metadata.get('score') or 0.0
            parsed.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": score
            })
        return parsed


class DefaultVectorProcessor(BaseRetrievalProcessor):
    """
    轻量级的标准文档提取，仅依赖简单的 Dense Vector Search。
    """
    def __init__(self, top_k: int):
        super().__init__(top_k)
        self.collection_name = settings.KB_VECTOR_TABLE
        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=self.collection_name,
            connection=get_engine(),
            use_jsonb=True
        )

    async def _vector_search(self, query: str, filters: Dict[str, Any]) -> List[Document]:
        try:
            model_name = getattr(self.embeddings, 'model', getattr(self.embeddings, 'model_name', settings.KB_EMBEDDING_MODEL))
            limiter = await LimiterRegistry.get_limiter(f"embedding:{model_name}", settings.KB_EMBEDDING_RPM)
            
            async with limiter:
                # 1. 显式获取 Embedding 向量 (调用公共工厂方法)
                safe_query = str(query).strip() or " "
                logger.info(f"🔍 [DefaultVectorProcessor] 请求 Embedding, Model=[{model_name}], QueryLen={len(safe_query)}")
                
                embeddings = await LLMFactory.aembed_texts_manual(
                    texts=[safe_query],
                    model_name=model_name,
                    api_key=settings.KB_API_KEY,
                    base_url=settings.KB_BASE_URL
                )
                query_vector = embeddings[0]

                # 2. 使用解析出的向量进行搜索
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        results = await self.vector_store.asimilarity_search_with_score_by_vector(
                            embedding=query_vector,
                            k=self.top_k,
                            filter=filters
                        )
                        break
                    except Exception as e:
                        if attempt == max_retries:
                            raise e
                        logger.warning(f"Vector search attempt {attempt + 1} failed, retrying... Error: {e}")
                        # 尝试重置引擎
                        from app.core.database import reset_engine
                        reset_engine()
                
                docs = []
                for doc, score in results:
                    doc.metadata['score'] = score
                    docs.append(doc)
                return docs
        except Exception as e:
            logger.error(f"PGVector 相似度搜索失败: {e}")
            raise RuntimeError(f"Vector search failed: {e}")


class HowToCookRetrievalProcessor(BaseRetrievalProcessor):
    """
    食谱检索器定制策略：加入了 Hybrid Search(基于局部的内存倒排树 BM25) + RRF 重排技术方案。
    大幅弥补专业烹饪术语使用纯向量召回容易发生“同义不同字”的漏网之鱼问题。
    """
    def __init__(self, top_k: int):
        super().__init__(top_k)
        self.collection_name = settings.KB_VECTOR_TABLE
        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=self.collection_name,
            connection=get_engine(),
            use_jsonb=True
        )
        self.rrf_k = 60  # RRF 的算法惩罚常量因子

    async def _vector_search(self, query: str, filters: Dict[str, Any]) -> List[Document]:
        # 为 RRF 需要更深度的蓄水池 (召回数量是最终 top_k 的 3-5 倍，以便做 BM25 再次排序)
        pool_size = self.top_k * 5
        try:
            model_name = getattr(self.embeddings, 'model', getattr(self.embeddings, 'model_name', settings.KB_EMBEDDING_MODEL))
            limiter = await LimiterRegistry.get_limiter(f"embedding:{model_name}", settings.KB_EMBEDDING_RPM)
            
            async with limiter:
                # 1. 手动获取 Query 向量（绕过 LangChain 内部参数坑）
                import httpx
                async with httpx.AsyncClient(verify=False) as client:
                    headers = {
                        "Authorization": f"Bearer {settings.KB_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": model_name,
                        "input": [query] # 注意：接口期望 list
                    }
                    resp = await client.post(f"{settings.KB_BASE_URL}/embeddings", json=payload, headers=headers, timeout=30.0)
                    if resp.status_code != 200:
                        raise RuntimeError(f"Retrieval Embedding Error {resp.status_code}: {resp.text}")
                    
                    query_vector = resp.json()["data"][0]["embedding"]

                # 2. 使用向量直接搜索
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        results = await self.vector_store.asimilarity_search_with_score_by_vector(
                            embedding=query_vector,
                            k=pool_size,
                            filter=filters
                        )
                        break
                    except Exception as e:
                        if attempt == max_retries:
                            raise e
                        logger.warning(f"Hybrid vector search attempt {attempt + 1} failed, retrying... Error: {e}")
                        from app.core.database import reset_engine
                        reset_engine()
            
            docs = []
            for doc, score in results:
                doc.metadata['score'] = score
                docs.append(doc)
            return docs
            
        except Exception as e:
            logger.error(f"HowToCook Hybrid Vector Pool 提取异常: {e}")
            raise RuntimeError(f"HowToCook 混合搜索骨架加载失败: {e}")

    async def _rerank_results(self, query: str, docs: List[Document]) -> List[Document]:
        if not docs:
            return []
            
        try:
            from langchain_community.retrievers import BM25Retriever
        except ImportError:
            logger.warning("并未安装 rank_bm25 模块，降级为普通向量搜索返回。")
            return docs

        # 1. 基于上一步过滤出的“局部上下文文档子集”迅速构建 BM25 Sparse 检索器
        # (这种做法完美避免了将全部数据读取进内存构建，性能好且安全)
        bm25_retriever = BM25Retriever.from_documents(docs, k=len(docs))
        
        # 2. 从集合抽取关键词词频热度高的 Document 排名
        bm25_hits = bm25_retriever.invoke(query)
        
        # 3. RRF (Reciprocal Rank Fusion) 深度重排打分
        doc_scores = {}
        doc_objects = {}

        # a) 按向量位置给分
        for rank, doc in enumerate(docs):
            doc_id = hash(doc.page_content)
            doc_objects[doc_id] = doc
            
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

        # b) 按 BM25 排名给分
        for rank, doc in enumerate(bm25_hits):
            doc_id = hash(doc.page_content)
            
            rrf_score = 1.0 / (self.rrf_k + rank + 1)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

        # 4. 根据最终聚合的 RRF 得分降序并返回
        sorted_scores = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        reranked_docs = []
        for doc_id, final_score in sorted_scores:
            if doc_id in doc_objects:
                doc = doc_objects[doc_id]
                doc.metadata['rrf_score'] = final_score
                reranked_docs.append(doc)

        logger.info(f"[HowToCook Hybrid RRF] 完成 RRF 重拍，原始池 {len(docs)} 个文档，合并输出前 {self.top_k}。")
        return reranked_docs


class RetrievalService:
    """
    业务逻辑服务容器，管理着分类策略的具体实例分发。
    """
    def __init__(self):
        pass

    async def search(self, query: str, category: Optional[str] = None, tenant_id: str = "default", top_k: int = 5) -> List[Dict[str, Any]]:
        filters = {}
        if tenant_id and tenant_id != "default":
            filters["tenant_id"] = tenant_id
        if category:
            filters["category"] = category

        # 依照条件智能分流
        if category and category.lower() in ["howtocook", "recipe"]:
            processor = HowToCookRetrievalProcessor(top_k=top_k)
        else:
            processor = DefaultVectorProcessor(top_k=top_k)
            
        return await processor.search(query, filters)
