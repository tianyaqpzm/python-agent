import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.core.llm_factory import LLMFactory
from app.services.kb.retrieval import RetrievalService, DefaultVectorProcessor
from app.services.kb.indexing import IndexingService, DefaultPGVectorProcessor
from langchain_core.documents import Document

@pytest.mark.asyncio
async def test_llm_factory_aembed_texts_manual():
    """测试手动向量化工具"""
    texts = ["hello", "world"]
    mock_embeddings = [
        {"embedding": [0.1, 0.2]},
        {"embedding": [0.3, 0.4]}
    ]
    
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": mock_embeddings}
        )
        
        vectors = await LLMFactory.aembed_texts_manual(
            texts=texts,
            model_name="test-model",
            api_key="test-key",
            base_url="https://api.example.com"
        )
        
        assert len(vectors) == 2
        assert vectors[0] == [0.1, 0.2]
        assert vectors[1] == [0.3, 0.4]
        mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_retrieval_service_search_empty_query():
    """测试检索服务处理空查询"""
    service = RetrievalService()
    results = await service.search(query="  ", category="test")
    assert results == []

@pytest.mark.asyncio
async def test_default_vector_processor_search():
    """测试向量检索处理器流程"""
    # 模拟 LLMFactory 的手动向量获取
    mock_vector = [0.1, 0.2, 0.3]
    
    with patch("app.core.llm_factory.LLMFactory.aembed_texts_manual", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [mock_vector]
        
        # 模拟 VectorStore
        mock_store = MagicMock()
        mock_store.asimilarity_search_with_score_by_vector = AsyncMock(return_value=[
            (Document(page_content="content1", metadata={"id": 1}), 0.9),
            (Document(page_content="content2", metadata={"id": 2}), 0.8),
        ])
        
        processor = DefaultVectorProcessor(top_k=5)
        # 手动注入 mock
        processor.embeddings = MagicMock()
        processor.vector_store = mock_store
        
        docs = await processor.search(query="test query", filters={})
        
        assert len(docs) == 2
        assert docs[0]["content"] == "content1"
        assert docs[0]["score"] == 0.9
        mock_embed.assert_called_once()
        mock_store.asimilarity_search_with_score_by_vector.assert_called_once()

@pytest.mark.asyncio
async def test_default_pgvector_processor_indexing():
    """测试索引构建处理器流程"""
    mock_vectors = [[0.1, 0.2], [0.3, 0.4]]
    
    with patch("app.core.llm_factory.LLMFactory.aembed_texts_manual", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = mock_vectors
        
        mock_store = MagicMock()
        mock_store.aadd_embeddings = AsyncMock()
        
        processor = DefaultPGVectorProcessor()
        processor.vector_store = mock_store
        
        chunks = [
            Document(page_content="text1", metadata={"source": "doc1"}),
            Document(page_content="text2", metadata={"source": "doc2"}),
        ]
        
        count = await processor._save_to_store(chunks)
        
        assert count == 2
        mock_embed.assert_called_once()
        mock_store.aadd_embeddings.assert_called_once()
