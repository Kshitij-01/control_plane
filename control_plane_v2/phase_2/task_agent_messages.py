"""
Task Agent Message Protocol
Real message types for boss-worker communication
"""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union


class TaskMessage(BaseModel):
    """Message from Orchestrator to Boss Agent"""
    task_id: str
    task_description: str
    input_files: List[str]
    expected_outputs: List[str]
    context: Optional[Dict[str, Any]] = None
    credentials: Optional[Dict[str, Any]] = None  # Database/API credentials from manifest


class SubtaskMessage(BaseModel):
    """Message from Boss Agent to Worker Agent"""
    subtask_id: str
    subtask_description: str
    input_files: List[str]
    instructions: str
    parent_task_id: str
    expected_outputs: Optional[List[str]] = None  # EXPLICIT list of files Boss expects Worker to create
    credentials: Optional[Dict[str, Any]] = None  # Database/API credentials passed from Boss


class SubtaskContinueMessage(BaseModel):
    """Message from Boss to Worker to continue with feedback (preserve state)"""
    subtask_id: str
    feedback: str
    continue_from_attempt: int
    preserve_kernel: bool = True
    existing_files_reminder: Optional[str] = None
    todo_reminder: Optional[str] = None


class SubtaskCompletionMessage(BaseModel):
    """Message from Worker Agent to Boss Agent - Simple completion report"""
    subtask_id: str
    status: str  # "success" or "gave_up"
    files_created: List[Union[str, Dict[str, str]]]  # Files Worker created (can be strings or dicts with filename/absolute_path)
    summary: str  # Brief summary of what was done
    gave_up: bool = False  # True if Claude decided task is impossible
    gave_up_reason: Optional[str] = None  # Why Claude gave up
    attempts_made: int = 1  # How many times Worker tried


class TaskCompletionMessage(BaseModel):
    """Message from Boss Agent to Orchestrator"""
    task_id: str
    status: str  # "completed", "failed", "partial"
    summary: str
    task_files_json_path: str
    files_created: List[str]

