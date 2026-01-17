TODO_WRITE_TOOL_DESCRIPTION = """
Use this tool to create and manage a structured task list for test execution. This helps track progress, organize complex test scenarios, and ensure thorough coverage.

### When to Use This Tool

Use proactively for:
1. Complex multi-step test scenarios (3+ distinct steps)
2. Non-trivial test flows requiring careful planning
3. After receiving new test requirements - capture them as todos (use merge=false for new test)
4. After completing tasks - mark as completed with merge=true
5. When starting new tasks - mark as in_progress (ideally only one at a time)

### When NOT to Use

Skip for:
1. Single, straightforward actions
2. Trivial tasks with no organizational benefit
3. Tasks completable in < 3 simple steps

### Task Types

**ACTION**: Steps that perform operations and change app state
- Navigate to screen
- Click button/element
- Enter text
- Swipe/scroll
- Launch/close app

**VERIFY**: Steps that validate/assert the current state
- Verify element is visible
- Assert text matches expected
- Confirm navigation succeeded
- Check error message appears

### Examples

**Example 1: Login Test Flow**
{
  "merge": false,
  "todos": [
    {
      "id": "1",
      "content": "Launch the app and navigate to login screen",
      "status": "pending",
      "todo_type": "action",
      "dependencies": []
    },
    {
      "id": "2",
      "content": "Verify login form is visible with username and password fields",
      "status": "pending",
      "todo_type": "verify",
      "dependencies": ["1"]
    },
    {
      "id": "3",
      "content": "Enter username 'testuser' in username field",
      "status": "pending",
      "todo_type": "action",
      "dependencies": ["2"]
    },
    {
      "id": "4",
      "content": "Enter password 'Test123!' in password field",
      "status": "pending",
      "todo_type": "action",
      "dependencies": ["2"]
    },
    {
      "id": "5",
      "content": "Tap the login button",
      "status": "pending",
      "todo_type": "action",
      "dependencies": ["3", "4"]
    },
    {
      "id": "6",
      "content": "Verify successful navigation to dashboard/home screen",
      "status": "pending",
      "todo_type": "verify",
      "dependencies": ["5"]
    }
  ]
}

**Example 2: Game Flow Test**
{
  "merge": false,
  "todos": [
    {
      "id": "1",
      "content": "Launch game and verify start screen is displayed",
      "status": "pending",
      "todo_type": "verify",
      "dependencies": []
    },
    {
      "id": "2",
      "content": "Tap 'New Game' button to start game",
      "status": "pending",
      "todo_type": "action",
      "dependencies": ["1"]
    },
    {
      "id": "3",
      "content": "Verify game screen loads with interactive elements",
      "status": "pending",
      "todo_type": "verify",
      "dependencies": ["2"]
    },
    {
      "id": "4",
      "content": "Perform first game action (e.g., tap first word/tile)",
      "status": "pending",
      "todo_type": "action",
      "dependencies": ["3"]
    },
    {
      "id": "5",
      "content": "Verify game responds to interaction correctly",
      "status": "pending",
      "todo_type": "verify",
      "dependencies": ["4"]
    }
  ]
}

### Task States

- **pending**: Not yet started
- **in_progress**: Currently working on
- **completed**: Finished successfully
- **cancelled**: No longer needed

### Task Management Rules

1. Update status in real-time as you work
2. Mark tasks as 'completed' IMMEDIATELY after finishing
3. Keep only ONE task 'in_progress' at a time
4. Complete current tasks before starting new ones
5. Use dependencies to ensure proper execution order

### Merge vs Replace

**merge: false** - Create new todo list (replaces existing)
- Starting a new test scenario
- Previous test is complete
- Changing test approach entirely

**merge: true** - Add/update todos in existing list
- Adding more detailed steps
- Updating task status
- Refining existing tasks

When in doubt, use this tool. Proactive task management ensures complete test coverage.
"""

TODO_WRITE_INPUT_DESCRIPTION = """
Input should be a JSON string with the following structure:
{
  "merge": boolean,
  "todos": [
    {
      "id": "unique_task_id",
      "content": "Detailed description of the task",
      "status": "pending" | "in_progress" | "completed" | "cancelled",
      "todo_type": "action" | "verify",
      "dependencies": ["id1", "id2"]
    }
  ]
}

### When to create a new list? (merge: false)
1. Starting a completely new test scenario
2. Previous test is fully completed (all tasks completed/cancelled)
3. Discovered new information that invalidates previous approach
4. User requests a different testing strategy

### When to add/update in current list? (merge: true)
1. Adding more granular steps to existing flow
2. Updating task status (marking completed, in_progress, etc.)
3. Adding follow-up tasks based on discoveries
4. Refining existing tasks with more detail
"""
