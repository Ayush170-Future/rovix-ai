from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class TodoType(Enum):
    """Type of todo task"""
    ACTION = "action"
    VERIFY = "verify"


class TodoStatus(Enum):
    """Status of todo task"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TodoItem:
    """Represents a single todo task"""
    id: str
    content: str
    status: TodoStatus
    todo_type: TodoType
    dependencies: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "todo_type": self.todo_type.value,
            "dependencies": self.dependencies
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TodoItem':
        """Create TodoItem from dictionary"""
        return cls(
            id=data["id"],
            content=data["content"],
            status=TodoStatus(data["status"]),
            todo_type=TodoType(data["todo_type"]),
            dependencies=data.get("dependencies", [])
        )


@dataclass
class TodoValidationResult:
    """Result of todo validation"""
    is_valid: bool
    error: Optional[str] = None


@dataclass
class TodoMergeOptions:
    """Options for merging todo lists"""
    resolve_dependencies: bool = False
