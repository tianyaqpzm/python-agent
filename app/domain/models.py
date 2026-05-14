from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

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
