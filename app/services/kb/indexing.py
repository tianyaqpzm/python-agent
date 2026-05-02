import logging
from typing import List, Optional
from abc import ABC, abstractmethod
from langchain_core.documents import Document
from langchain_postgres import PGVector
from app.core.config import settings
from app.core.llm_factory import LLMFactory
from app.core.database import get_engine

logger = logging.getLogger(__name__)


class BaseIndexingProcessor(ABC):
    """
    索引构建处理器的抽象基类，使用模板方法模式 (Template Method Pattern)。
    规范了向量及元数据入库的核心流程。
    """

    def __init__(self, embedding_model: Optional[str] = None):
        # 统一获取配置好的 Embeddings 实例
        provider = settings.KB_EMBEDDING_PROVIDER
        model = embedding_model if embedding_model else settings.KB_EMBEDDING_MODEL
        
        self.embeddings = LLMFactory.get_embedding_model(
            provider=settings.KB_EMBEDDING_PROVIDER,
            model_name=settings.KB_EMBEDDING_MODEL,
            api_key=settings.KB_API_KEY,
            base_url=settings.KB_BASE_URL,
        )

    async def process(self, chunks: List[Document]) -> int:
        """
        模板方法：规定文档构建索引的生命周期
        """
        if not chunks:
            logger.warning(f"[{self.__class__.__name__}] 接收到空的 chunks 列表，跳过索引建构。")
            return 0
            
        logger.info(f"[{self.__class__.__name__}] 3.开始为 {len(chunks)} 个分块建立索引...")
        
        # 1. 前置验证或特征提取 (Hook)
        self._pre_index(chunks)
        
        # 2. 执行核心存储
        inserted_count = await self._save_to_store(chunks)
        
        logger.info(f"[{self.__class__.__name__}] 4.索引写入完成，成功记录 {inserted_count} 条。")
        return inserted_count

    def _pre_index(self, chunks: List[Document]) -> None:
        """【可选覆盖】钩子方法：可以在实际调用底层连接库前再次修改或验证 Chunk Metadata"""
        pass

    @abstractmethod
    async def _save_to_store(self, chunks: List[Document]) -> int:
        """【强制实现】把 Embedding 和 Payload 写到具体的向量引擎驱动（如 PGVector, FAISS, Milvus）"""
        pass


class DefaultPGVectorProcessor(BaseIndexingProcessor):
    """
    标准的 PostgreSQL pgvector 本地/远程索引存储引擎处理器。
    """
    def __init__(self, embedding_model: Optional[str] = None):
        super().__init__(embedding_model)
        self.collection_name = settings.KB_VECTOR_TABLE
        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=self.collection_name,
            connection=get_engine(),
            use_jsonb=True,
        )

    async def _save_to_store(self, chunks: List[Document]) -> int:
        from app.core.limiter import LimiterRegistry
        
        # 0. 防御性过滤：剔除 page_content 为空的分块，避免 Embedding 接口报错 "input is empty"
        valid_chunks = [c for c in chunks if c.page_content and c.page_content.strip()]
        if len(valid_chunks) < len(chunks):
            logger.warning(f"⚠️ 过滤掉 {len(chunks) - len(valid_chunks)} 个内容为空或全为空格的分块")
        
        if not valid_chunks:
            return 0

        batch_size = 50 # 建议每批 50-100 个分块，避免单次请求过大
        inserted_total = 0
        
        try:
            target_url = f"{settings.KB_BASE_URL}/embeddings"
            model_name = getattr(self.embeddings, 'model', settings.KB_EMBEDDING_MODEL)
            
            # 架构级公共能力：通过 Registry 获取针对该模型的唯一限流器
            limiter = await LimiterRegistry.get_limiter(f"embedding:{model_name}", settings.KB_EMBEDDING_RPM)
            
            for i in range(0, len(valid_chunks), batch_size):
                batch = valid_chunks[i : i + batch_size]
                
                async with limiter:
                    texts = [c.page_content for c in batch]
                    metadatas = [c.metadata for c in batch]
                    
                    logger.info(f"🚀 发起向量化请求 [批次 {i//batch_size + 1}]: URL={target_url}, Model={model_name}, BatchSize={len(batch)}")
                    
                    # 1. 手动获取向量（绕过 LangChain 内部参数坑）
                    import httpx
                    async with httpx.AsyncClient(verify=False) as client:
                        headers = {
                            "Authorization": f"Bearer {settings.KB_API_KEY}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "model": model_name,
                            "input": texts
                        }
                        resp = await client.post(f"{settings.KB_BASE_URL}/embeddings", json=payload, headers=headers, timeout=60.0)
                        if resp.status_code != 200:
                            raise RuntimeError(f"Embedding API Error {resp.status_code}: {resp.text}")
                        
                        embeddings_data = resp.json()["data"]
                        embeddings = [item["embedding"] for item in embeddings_data]
                    
                    # 2. 直接注入向量到数据库
                    await self.vector_store.aadd_embeddings(
                        texts=texts,
                        embeddings=embeddings,
                        metadatas=metadatas
                    )
                    inserted_total += len(batch)
                
            return inserted_total
        except Exception as e:
            # 打印更详细的错误上下文
            logger.error(f"❌ 向量化回写失败！已完成: {inserted_total}/{len(chunks)}")
            
            # 打印当前失败批次的请求体内容
            failed_batch = [c.page_content[:100] for c in chunks[inserted_total:inserted_total+batch_size]]
            logger.error(f"失败批次预览 (Chunks): {failed_batch}")
            
            logger.error(f"异常详情: {e}")
            raise RuntimeError(f"PGVector Write Failed: {e}")


class IndexingService:
    """
    策略路由层：目前我们的持久化层单一，所以直接路由给 PGVector 实现。
    如果未来要做混合存储（例如配置了 FAISS 缓存表 + Milvus）可以在此判断 category 动态发牌。
    """
    def __init__(self):
        pass

    async def build_and_save_index(self, chunks: List[Document], category: str = "default", embedding_model: Optional[str] = None, vector_store: Optional[str] = None) -> int:
        """根据策略路由建立索引"""
        # 可以基于 Category 进行定制化的 DB 表分配，此处简化复用统一的 DefaultPGVector
        processor = DefaultPGVectorProcessor(embedding_model=embedding_model)
        return await processor.process(chunks)
