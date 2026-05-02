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
        
        self.embeddings = LLMFactory.get_embeddings(
            provider=provider,
            model_name=model,
            base_url=settings.LLM_BASE_URL
        )

    async def process(self, chunks: List[Document]) -> int:
        """
        模板方法：规定文档构建索引的生命周期
        """
        if not chunks:
            logger.warning(f"[{self.__class__.__name__}] 接收到空的 chunks 列表，跳过索引建构。")
            return 0
            
        logger.info(f"[{self.__class__.__name__}] 开始为 {len(chunks)} 个分块建立索引...")
        
        # 1. 前置验证或特征提取 (Hook)
        self._pre_index(chunks)
        
        # 2. 执行核心存储
        inserted_count = await self._save_to_store(chunks)
        
        logger.info(f"[{self.__class__.__name__}] 索引写入完成，成功记录 {inserted_count} 条。")
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
        try:
            # aadd_documents 底层会自动处理批量插入（Batch Insert）
            await self.vector_store.aadd_documents(chunks)
            return len(chunks)
        except Exception as e:
            logger.error(f"构建或写入 PGVector 向量索引时出现异常: {e}")
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
