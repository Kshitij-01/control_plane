"""
Messages for Phase 1 → Phase 2Z communication using Pydantic
Following AutoGen Core messaging patterns
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class SubtaskPlan(BaseModel):
    """A single subtask in the execution plan"""
    id: str
    task_category: str  # independent, sequential_first, sequential_last
    description: str
    chain_ids: List[int] = Field(default_factory=list)
    columns_needed: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    outputs_produced: List[str] = Field(default_factory=list)
    complexity: str = "moderate"
    estimated_duration: str = "unknown"


class ExecutionPlanMessage(BaseModel):
    """Message from Phase 1 to Phase 2Z with complete execution plan"""
    task_id: str
    
    # Flexible plan structure from Phase 1b (Claude/GPT-5 defined)
    plan: Dict[str, Any]  # Can be any logical structure
    
    # Structure analysis from Phase 1a
    structure_analysis: Dict[str, Any] = Field(default_factory=dict)
    
    # Credentials for workers
    credentials: Dict[str, Any] = Field(default_factory=dict)
    
    # Data/context for workers (e.g., mapping_plan.json content)
    transformation_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Workspace info
    workspace_root: str
    
    # Additional context
    additional_context: Dict[str, Any] = Field(default_factory=dict)
    
    # Legacy fields (optional for backward compatibility)
    can_be_divided: bool = True
    reasoning: str = ""
    subtasks: List[SubtaskPlan] = Field(default_factory=list)
    execution_strategy: str = "flexible"


class ExecutionCompletionMessage(BaseModel):
    """Message from Phase 2Z back to Phase 1 with execution results"""
    task_id: str
    overall_status: str  # success, partial_success, failure
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    task_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    execution_time: float = 0.0
    notes: str = ""

