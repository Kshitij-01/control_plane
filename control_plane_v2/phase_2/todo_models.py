"""
Pydantic models for TODO system
"""
from typing import List, Literal
from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    """Single TODO item"""
    id: str = Field(..., description="Unique identifier for the TODO item")
    content: str | None = Field(default=None, description="Description of the task to complete")
    status: Literal["pending", "in_progress", "completed", "cancelled"] = Field(
        default="pending",
        description="Current status of the TODO item"
    )


class TodoList(BaseModel):
    """Complete TODO list"""
    todos: List[TodoItem] = Field(..., description="List of TODO items")
    
    def get_pending(self) -> List[TodoItem]:
        """Get all pending or in-progress TODOs"""
        return [t for t in self.todos if t.status in ["pending", "in_progress"]]
    
    def get_completed(self) -> List[TodoItem]:
        """Get all completed TODOs"""
        return [t for t in self.todos if t.status == "completed"]
    
    def is_complete(self) -> bool:
        """Check if all TODOs are completed"""
        return len(self.get_pending()) == 0
    
    def get_by_id(self, todo_id: str) -> TodoItem | None:
        """Get TODO by ID"""
        for todo in self.todos:
            if todo.id == todo_id:
                return todo
        return None
    
    def update_status(self, todo_id: str, new_status: str) -> bool:
        """Update status of a TODO item"""
        todo = self.get_by_id(todo_id)
        if todo:
            todo.status = new_status
            return True
        return False


class TodoWriteRequest(BaseModel):
    """Request to write/update TODO list"""
    workspace_path: str = Field(..., description="Workspace path where TODO file will be stored")
    merge: bool = Field(default=False, description="Whether to merge with existing todos")
    todos: List[TodoItem] = Field(..., description="List of TODO items to write")


class TodoWriteResponse(BaseModel):
    """Response from TODO write operation"""
    success: bool = Field(..., description="Whether the operation succeeded")
    message: str = Field(..., description="Success or error message")
    todos_count: int = Field(default=0, description="Number of TODO items written")

