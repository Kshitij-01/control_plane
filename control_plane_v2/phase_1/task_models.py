"""
Pydantic models for Phase 1 task division structures
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class WorkScope(BaseModel):
    inputs: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    outputs_description: str = ""


class Credentials(BaseModel):
    filesystem: str = "local"
    no_external_credentials: bool = True


class SubtaskDefinition(BaseModel):
    task_id: str
    description: str
    work_scope: WorkScope
    credentials: Credentials = Field(default_factory=Credentials)
    dependencies: List[str] = Field(default_factory=list)
    expected_output_files: List[str] = Field(default_factory=list)


class TaskBreakdown(BaseModel):
    tasks: List[SubtaskDefinition] = Field(default_factory=list, description="Simple list of all tasks. Orchestrator determines execution order from dependencies.")


class TaskDivisionProposal(BaseModel):
    task_breakdown: TaskBreakdown
    reasoning: Optional[str] = None
    confidence: Optional[str] = None


class ReviewResult(BaseModel):
    approved: bool
    feedback: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    confidence: Optional[str] = None
