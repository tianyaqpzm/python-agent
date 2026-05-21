from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

@dataclass(eq=False)
class ChatMessage:
    """Pure domain model for chat messages."""
    role: str  # 'user' or 'ai'
    content: str
    session_id: str
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.role in ['user', 'ai']:
            raise ValueError(f"Invalid role: {self.role}")
        if not self.content:
            raise ValueError("Content cannot be empty")

    def __eq__(self, other):
        if not isinstance(other, ChatMessage):
            return NotImplemented
        if self.id is None or other.id is None:
            return self is other
        return self.id == other.id

    def __hash__(self):
        if self.id is None:
            return hash(id(self))
        return hash(self.id)

@dataclass(frozen=True)
class ServiceInstance:
    """Value object representing a service instance from Nacos."""
    ip: str
    port: int
    instance_id: Optional[str] = None
    weight: float = 1.0
    healthy: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.ip:
            raise ValueError("IP address is required")
        if not (0 <= self.port <= 65535):
            raise ValueError(f"Invalid port: {self.port}")

@dataclass(eq=False)
class TaskRecord:
    """Pure domain model for background task records (Rich Domain Model)."""
    id: str
    task_type: str
    status: str = "RUNNING"
    total_count: int = 0
    processed_count: int = 0
    current_item_name: Optional[str] = None
    error_message: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("Task ID is required")
        if not self.task_type:
            raise ValueError("Task type is required")
        if self.status not in ["RUNNING", "SUCCESS", "FAILED"]:
            raise ValueError(f"Invalid task status: {self.status}")
        if self.processed_count < 0:
            raise ValueError("Processed count cannot be negative")

    def update_progress(self, total_count: int, processed_count: int, current_item_name: Optional[str]):
        if processed_count < 0:
            raise ValueError("Processed count cannot be negative")
        self.total_count = total_count
        self.processed_count = processed_count
        self.current_item_name = current_item_name
        self.update_time = datetime.now()

    def complete(self):
        self.status = "SUCCESS"
        self.update_time = datetime.now()

    def fail(self, error_message: str):
        self.status = "FAILED"
        self.error_message = error_message
        self.update_time = datetime.now()

    def __eq__(self, other):
        if not isinstance(other, TaskRecord):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)


@dataclass(eq=False)
class KnowledgeDocument:
    """Pure domain model for generic knowledge documents."""
    file_path: str
    file_hash: str
    doc_type: str
    title: str
    category: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None
    topic_id: Optional[str] = None

    def __post_init__(self):
        if not self.file_path:
            raise ValueError("File path is required")
        if not self.file_hash:
            raise ValueError("File hash is required")
        if not self.doc_type:
            raise ValueError("Document type is required")
        if not self.title:
            raise ValueError("Title is required")
        if not isinstance(self.metadata, dict):
            raise TypeError("Metadata must be a dictionary")

    def __eq__(self, other):
        if not isinstance(other, KnowledgeDocument):
            return NotImplemented
        if self.id is None or other.id is None:
            return self is other
        return self.id == other.id

    def __hash__(self):
        if self.id is None:
            return hash(id(self))
        return hash(self.id)


@dataclass(eq=False)
class KnowledgeChunk:
    """Pure domain model for knowledge document chunks."""
    document_id: str
    chunk_index: int
    content: str
    embedding: List[float] = field(default_factory=list)
    id: Optional[int] = None

    def __post_init__(self):
        if self.document_id is None:
            raise ValueError("Document ID is required")
        if self.chunk_index < 0:
            raise ValueError("Chunk index cannot be negative")
        if not self.content:
            raise ValueError("Content cannot be empty")

    def __eq__(self, other):
        if not isinstance(other, KnowledgeChunk):
            return NotImplemented
        if self.id is None or other.id is None:
            return self is other
        return self.id == other.id

    def __hash__(self):
        if self.id is None:
            return hash(id(self))
        return hash(self.id)
