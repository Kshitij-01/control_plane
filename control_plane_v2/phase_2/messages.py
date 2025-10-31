"""
Pydantic message models for Phase 2: Collaborative Code Execution

Following AutoGen best practices for message-based communication:
https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/message-and-communication.html
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field, validator

# Import shared models
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.models import ArtifactRef, TaskMetrics


class ClaudeCodeResponse(BaseModel):
    """
    Claude's code generation response.
    
    Validates that Claude provides all required fields for code execution.
    """
    code: str = Field(..., description="The generated Python code to execute")
    explanation: str = Field("", description="Human-readable explanation of what the code does (optional)")
    approach: Union[str, List[str]] = Field("", description="High-level approach or strategy used (optional)")
    
    @validator('code')
    def validate_code_not_empty(cls, v):
        """Ensure code is not empty"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Code cannot be empty - at minimum provide a print statement")
        # Removed length limit - give full freedom
        return v


class GPT5ReviewResponse(BaseModel):
    """
    GPT-5's code review response.
    
    Validates that GPT-5 provides a clear verdict and reasoning.
    """
    approved: bool = Field(..., description="Whether the code is approved for execution")
    confidence: float = Field(0.5, description="Confidence in the approval decision (0-1), defaults to 0.5")
    reasoning: str = Field("", description="Detailed reasoning for the decision (optional)")
    concerns: List[str] = Field(default_factory=list, description="List of concerns or issues identified")
    suggestions: List[str] = Field(default_factory=list, description="Suggestions for improvement")


class GPT5DebugResponse(BaseModel):
    """
    GPT-5's debugging response when code execution fails.
    
    Provides root cause analysis and fix suggestions.
    """
    root_cause: str = Field("", description="Root cause analysis of the error (optional)")
    fix_suggestions: List[str] = Field(default_factory=list, description="Specific suggestions to fix the error")
    spatial_analysis: Optional[str] = Field(None, description="Analysis of where the error occurs in the code (line numbers)")
    similar_patterns: Optional[str] = Field(None, description="Reference to similar errors seen before")


class ClaudeStructureAnalysis(BaseModel):
    """
    Claude's structure analysis response (Phase 1a).
    
    Analysis of task structure and data dependencies.
    """
    analysis_complete: bool = Field(..., description="Whether the analysis is complete")
    structure_summary: str = Field(..., description="Summary of the analyzed structure")
    data_sources: List[str] = Field(default_factory=list, description="Identified data sources")
    data_targets: List[str] = Field(default_factory=list, description="Identified data targets")
    key_entities: List[str] = Field(default_factory=list, description="Key entities or tables")
    transformation_complexity: str = Field("moderate", description="Complexity assessment: simple, moderate, complex")
    recommendations: List[str] = Field(default_factory=list, description="Recommendations for task execution")
    
    @validator('structure_summary')
    def validate_structure_summary_not_empty(cls, v):
        """Ensure structure summary is provided"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Structure summary cannot be empty")
        return v


class ClaudeTaskDivisionProposal(BaseModel):
    """
    Claude's task division proposal (Phase 1b).
    
    Proposal for how to divide a task into subtasks.
    """
    can_be_divided: bool = Field(..., description="Whether the task can be divided")
    reasoning: str = Field(..., description="Reasoning for the division strategy")
    subtasks: List[Dict[str, Any]] = Field(default_factory=list, description="List of proposed subtasks")
    execution_strategy: str = Field("dag", description="Execution strategy: sequential, parallel, dag")
    estimated_total_duration: str = Field("unknown", description="Estimated total duration")
    dependencies_explanation: str = Field("", description="Explanation of dependencies between subtasks")
    
    @validator('reasoning')
    def validate_reasoning_not_empty(cls, v):
        """Ensure reasoning is provided"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Reasoning cannot be empty")
        return v
    
    @validator('subtasks')
    def validate_subtasks_format(cls, v, values):
        """Ensure subtasks are properly formatted if task can be divided"""
        if values.get('can_be_divided', False) and len(v) == 0:
            raise ValueError("If task can be divided, subtasks must be provided")
        return v


class GPT5TaskDivisionReview(BaseModel):
    """
    GPT-5's review of Claude's task division proposal (Phase 1b).
    
    Review and validation of the proposed task division.
    """
    satisfied: bool = Field(..., description="Whether the proposal is satisfactory")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the review (0-1)")
    feedback: str = Field(..., description="Detailed feedback on the proposal")
    suggestions: List[str] = Field(default_factory=list, description="Suggestions for improvement")
    must_change: List[str] = Field(default_factory=list, description="Required changes before approval")
    
    @validator('feedback')
    def validate_feedback_not_empty(cls, v):
        """Ensure feedback is provided"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Feedback cannot be empty")
        return v


class TaskExecutionResult(BaseModel):
    """
    Result of a task execution (created by the executor after code runs).
    
    This is the standardized output format for all task executions.
    """
    task_id: str = Field(..., description="ID of the executed task")
    success: bool = Field(..., description="Whether the task executed successfully")
    exit_code: int = Field(0, description="Exit code of the execution")
    output: str = Field("", description="Standard output from the execution")
    error: str = Field("", description="Standard error from the execution")
    duration_seconds: float = Field(0.0, description="Execution duration in seconds")
    iterations_used: int = Field(1, description="Number of iterations used (including retries)")
    
    # NEW: Support both legacy and new artifact tracking
    files_created: List[str] = Field(default_factory=list, description="LEGACY: List of file paths created by the task")
    artifacts_created: List[ArtifactRef] = Field(default_factory=list, description="NEW: Artifact references with metadata")
    
    learnings: Dict[str, Any] = Field(default_factory=dict, description="Learnings from the task execution")
    metrics: Optional[TaskMetrics] = Field(None, description="NEW: Detailed execution metrics")
    
    # NEW: Contract validation results
    contract_validated: bool = Field(False, description="Whether output contract was validated")
    contract_violations: List[str] = Field(default_factory=list, description="Any contract violations found")
    
    @validator('task_id')
    def validate_task_id_not_empty(cls, v):
        """Ensure task ID is provided"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Task ID cannot be empty")
        return v


class SubtaskExecutionRequest(BaseModel):
    """
    Request for executing a subtask (sent from orchestrator to executor).
    
    Contains the package path and accumulated learnings.
    """
    package_path: str = Field(..., description="Path to the subtask package JSON file")
    accumulated_learnings: List[Dict[str, Any]] = Field(default_factory=list, description="Learnings from prior tasks")
