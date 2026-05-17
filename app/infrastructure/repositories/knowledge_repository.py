import json
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
            text("SELECT id, file_path, file_hash, doc_type, title, category, metadata FROM ms_knowledge_document WHERE file_path = :file_path"),
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
            metadata=meta
        )

    async def delete_by_id(self, doc_id: int) -> None:
        await self.session.execute(
            text("DELETE FROM ms_knowledge_document WHERE id = :id"),
            {"id": doc_id}
        )

    async def save_document(self, doc: KnowledgeDocument) -> int:
        insert_res = await self.session.execute(
            text("INSERT INTO ms_knowledge_document (file_path, file_hash, doc_type, title, category, metadata) "
                 "VALUES (:file_path, :file_hash, :doc_type, :title, :category, :metadata) RETURNING id"),
            {
                "file_path": doc.file_path,
                "file_hash": doc.file_hash,
                "doc_type": doc.doc_type,
                "title": doc.title,
                "category": doc.category,
                "metadata": json.dumps(doc.metadata) if doc.metadata else "{}"
            }
        )
        return insert_res.scalar()

    async def save_chunks(self, doc_id: int, chunks: List[str], embeddings: List[List[float]]) -> None:
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
