import json
import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import KnowledgeDocument
from app.domain.repositories import IKnowledgeRepository

class SqlAlchemyKnowledgeRepository(IKnowledgeRepository):
    """SQLAlchemy implementation of the Knowledge Repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_filepath(self, file_path: str) -> Optional[KnowledgeDocument]:
        res = await self.session.execute(
            text("SELECT id, file_path, file_hash, doc_type, title, category, metadata, topic_id FROM ms_knowledge_document WHERE file_path = :file_path"),
            {"file_path": file_path}
        )
        row = res.fetchone()
        if not row:
            return None
            
        raw_meta = row[6]
        if isinstance(raw_meta, str):
            try:
                meta = json.loads(raw_meta)
            except Exception:
                meta = {}
        elif isinstance(raw_meta, dict):
            meta = raw_meta
        else:
            meta = {}

        return KnowledgeDocument(
            id=row[0],
            file_path=row[1],
            file_hash=row[2],
            doc_type=row[3],
            title=row[4],
            category=row[5],
            metadata=meta,
            topic_id=row[7]
        )

    async def delete_by_id(self, doc_id: str) -> None:
        await self.session.execute(
            text("DELETE FROM ms_knowledge_document WHERE id = :id"),
            {"id": doc_id}
        )

    async def save_document(self, doc: KnowledgeDocument) -> str:
        doc_id = doc.id if doc.id else uuid.uuid4().hex
        
        topic_id = doc.topic_id
        if not topic_id:
            if doc.doc_type == "recipe":
                res = await self.session.execute(
                    text("SELECT id FROM ms_knowledge_topic WHERE name = '菜谱'")
                )
                row = res.fetchone()
                topic_id = row[0] if row else "bc35e6e9c9b44c7cac23661f70695038"
            else:
                res = await self.session.execute(
                    text("SELECT id FROM ms_knowledge_topic WHERE name = 'AI技术'")
                )
                row = res.fetchone()
                topic_id = row[0] if row else "e5daca5aa796410e93e8f629d6c764bc"

        await self.session.execute(
            text("INSERT INTO ms_knowledge_document (id, topic_id, file_path, file_hash, doc_type, title, category, metadata) "
                 "VALUES (:id, :topic_id, :file_path, :file_hash, :doc_type, :title, :category, :metadata)"),
            {
                "id": doc_id,
                "topic_id": topic_id,
                "file_path": doc.file_path,
                "file_hash": doc.file_hash,
                "doc_type": doc.doc_type,
                "title": doc.title,
                "category": doc.category,
                "metadata": json.dumps(doc.metadata) if doc.metadata else "{}"
            }
        )
        return doc_id

    async def save_chunks(self, doc_id: str, chunks: List[str], embeddings: List[List[float]]) -> None:
        for idx, (chunk_content, emb) in enumerate(zip(chunks, embeddings)):
            emb_str = f"[{','.join(map(str, emb))}]"
            await self.session.execute(
                text("INSERT INTO ms_knowledge_chunk (document_id, chunk_index, content, embedding) "
                     "VALUES (:doc_id, :idx, :content, CAST(:emb AS vector))"),
                {
                    "doc_id": doc_id,
                    "idx": idx,
                    "content": chunk_content,
                    "emb": emb_str
                }
            )
