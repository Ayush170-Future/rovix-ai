import json
from typing import Dict, Any
from .todo_types import TodoItem, TodoType, TodoStatus
from .todo_service import (
    TodoPersistenceService,
    validate_todo_item,
    merge_todo_lists,
    TodoMergeOptions
)


def todo_write_handler(input_str: str, session_id: str) -> str:
    """
    Main handler for todo_write tool.
    
    Input format:
    {
        "merge": bool,
        "todos": [
            {
                "id": str,
                "content": str,
                "status": str,
                "todo_type": str,
                "dependencies": [str]
            }
        ]
    }
    
    Returns JSON string with success status and task counts.
    """
    try:
        # 1. Parse input
        parsed_input = json.loads(input_str)
        
        # 2. Validate input structure
        if "merge" not in parsed_input:
            return json.dumps({
                "success": False,
                "message": "Missing 'merge' field"
            })
        
        if "todos" not in parsed_input or not isinstance(parsed_input["todos"], list):
            return json.dumps({
                "success": False,
                "message": "Missing or invalid 'todos' field"
            })
        
        if len(parsed_input["todos"]) == 0:
            return json.dumps({
                "success": False,
                "message": "At least one todo is required"
            })
        
        merge = parsed_input["merge"]
        
        # 3. Convert to TodoItem objects and validate
        todos = []
        validation_errors = []
        
        for todo_dict in parsed_input["todos"]:
            try:
                # Create TodoItem from dict
                todo = TodoItem(
                    id=todo_dict["id"],
                    content=todo_dict["content"],
                    status=TodoStatus(todo_dict["status"]),
                    todo_type=TodoType(todo_dict["todo_type"]),
                    dependencies=todo_dict.get("dependencies", [])
                )
                
                # Validate todo
                validation = validate_todo_item(todo)
                if not validation.is_valid:
                    validation_errors.append(f"Task {todo.id}: {validation.error}")
                else:
                    todos.append(todo)
                    
            except (KeyError, ValueError) as e:
                validation_errors.append(f"Invalid todo format: {str(e)}")
        
        if validation_errors:
            return json.dumps({
                "success": False,
                "message": f"Validation errors: {'; '.join(validation_errors)}"
            })
        
        # 4. Merge or replace
        if merge:
            existing_todos = TodoPersistenceService.get_todo_list(session_id)
            final_todos = merge_todo_lists(existing_todos, todos)
        else:
            final_todos = todos
        
        # 5. Save to storage
        saved_todos = TodoPersistenceService.save_todo_list(session_id, final_todos)
        
        # 6. Calculate task counts
        task_counts = get_task_counts(saved_todos)
        
        return json.dumps({
            "success": True,
            "message": "Todo list updated successfully",
            "totalTasks": len(saved_todos),
            "taskCounts": task_counts
        })
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "success": False,
            "message": f"Invalid JSON input: {str(e)}"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"Error processing todo list: {str(e)}"
        })


def get_task_counts(todos: list[TodoItem]) -> dict:
    """Calculate counts by status and type"""
    return {
        "pending": sum(1 for t in todos if t.status == TodoStatus.PENDING),
        "in_progress": sum(1 for t in todos if t.status == TodoStatus.IN_PROGRESS),
        "completed": sum(1 for t in todos if t.status == TodoStatus.COMPLETED),
        "cancelled": sum(1 for t in todos if t.status == TodoStatus.CANCELLED),
        "actions": sum(1 for t in todos if t.todo_type == TodoType.ACTION),
        "verifications": sum(1 for t in todos if t.todo_type == TodoType.VERIFY)
    }


def get_todo_list_for_context(session_id: str) -> str:
    """
    Get formatted todo list for LLM context.
    Returns human-readable string representation.
    """
    todos = TodoPersistenceService.get_todo_list(session_id)
    
    if not todos:
        return "No active todo list."
    
    output = ["Current Todo List:", ""]
    
    for todo in todos:
        status_text = {
            TodoStatus.PENDING: "[PENDING]",
            TodoStatus.IN_PROGRESS: "[IN_PROGRESS]",
            TodoStatus.COMPLETED: "[COMPLETED]",
            TodoStatus.CANCELLED: "[CANCELLED]"
        }.get(todo.status, "[UNKNOWN]")
        
        type_label = "ACTION" if todo.todo_type == TodoType.ACTION else "VERIFY"
        deps = f" (depends on: {', '.join(todo.dependencies)})" if todo.dependencies else ""
        
        output.append(f"{status_text} [{todo.id}] [{type_label}] {todo.content}{deps}")
    
    return "\n".join(output)
