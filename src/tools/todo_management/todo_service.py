from typing import Dict, List
from .todo_types import TodoItem, TodoStatus, TodoType, TodoValidationResult, TodoMergeOptions


class TodoPersistenceService:
    
    _storage: Dict[str, List[TodoItem]] = {}
    
    @staticmethod
    def save_todo_list(session_id: str, todos: List[TodoItem]) -> List[TodoItem]:
        TodoPersistenceService._storage[session_id] = todos
        return todos
    
    @staticmethod
    def get_todo_list(session_id: str) -> List[TodoItem]:
        return TodoPersistenceService._storage.get(session_id, [])
    
    @staticmethod
    def clear_todo_list(session_id: str) -> None:
        if session_id in TodoPersistenceService._storage:
            del TodoPersistenceService._storage[session_id]
    
    @staticmethod
    def get_all_sessions() -> List[str]:
        return list(TodoPersistenceService._storage.keys())


def validate_todo_item(todo: TodoItem) -> TodoValidationResult:
    if not todo.id or not todo.id.strip():
        return TodoValidationResult(is_valid=False, error="ID is required")
    
    if not todo.content or not todo.content.strip():
        return TodoValidationResult(is_valid=False, error="Content is required")
    
    if not isinstance(todo.status, TodoStatus):
        return TodoValidationResult(is_valid=False, error="Invalid status")
    
    if not isinstance(todo.todo_type, TodoType):
        return TodoValidationResult(is_valid=False, error="Invalid todo_type")
    
    if todo.id in todo.dependencies:
        return TodoValidationResult(is_valid=False, error="Task cannot depend on itself")
    
    return TodoValidationResult(is_valid=True)


def merge_todo_lists(
    existing_todos: List[TodoItem],
    new_todos: List[TodoItem],
    options: TodoMergeOptions | None = None
) -> List[TodoItem]:
    if options is None:
        options = TodoMergeOptions()
    
    merged = {todo.id: todo for todo in existing_todos}
    
    for new_todo in new_todos:
        merged[new_todo.id] = new_todo
    
    result = list(merged.values())
    
    if options.resolve_dependencies:
        result = resolve_dependencies(result)
    
    return result


def resolve_dependencies(todos: List[TodoItem]) -> List[TodoItem]:
    valid_ids = {todo.id for todo in todos}
    
    return [
        TodoItem(
            id=todo.id,
            content=todo.content,
            status=todo.status,
            todo_type=todo.todo_type,
            dependencies=[dep for dep in todo.dependencies if dep in valid_ids]
        )
        for todo in todos
    ]
