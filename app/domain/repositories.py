from abc import ABC, abstractmethod
from typing import Optional, List
from app.domain.models import KnowledgeDocument

class IKnowledgeRepository(ABC):
    """Abstract interface for Knowledge repository."""

    @abstractmethod
    async def find_by_filepath(self, file_path: str) -> Optional[KnowledgeDocument]:
        """Find a knowledge document by its relative file path."""
        pass

    @abstractmethod
    async def delete_by_id(self, doc_id: int) -> None:
        """Delete a knowledge document (and cascading chunks if any) by document ID."""
        pass

    @abstractmethod
    async def save_document(self, doc: KnowledgeDocument) -> int:
        """Insert a new knowledge document and return its new ID."""
        pass

    @abstractmethod
    async def save_chunks(self, doc_id: int, chunks: List[str], embeddings: List[List[float]]) -> None:
        """Batch save chunk contents and their corresponding vector embeddings."""
        pass
