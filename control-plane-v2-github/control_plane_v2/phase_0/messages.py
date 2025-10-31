"""
Message types for Phase 0 task classification and negotiation
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from .models import FileInfo, ConnectionInfo, TaskConstraints


class CoreTask(BaseModel):
    """A core task (the main work to be done)"""
    id: str
    description: str
    subtasks: List[str] = Field(default_factory=list)
    estimated_duration: Optional[str] = None
    can_be_divided: bool = False
    division_strategy: Optional[str] = None
    resource_requirements: Optional[Dict[str, Any]] = None
    dependencies: List[str] = Field(default_factory=list)


class SideTask(BaseModel):
    """A side task (prerequisite or verification)"""
    id: str
    description: str
    priority: str = "medium"  # critical, high, medium, low
    blocking: bool = True  # If True, must complete before core tasks
    estimated_duration: Optional[str] = None
    verification_needed: bool = True
    agent_generator_request: Optional[Dict[str, Any]] = None
    dependencies: List[str] = Field(default_factory=list)


class TaskAnalysisRequest(BaseModel):
    """Request to analyze and classify a task"""
    task_id: str
    task_description: str
    files: List[FileInfo] = Field(default_factory=list)
    connections: List[ConnectionInfo] = Field(default_factory=list)
    constraints: Optional[TaskConstraints] = None
    additional_context: Optional[Dict[str, Any]] = None


class TaskClassificationProposal(BaseModel):
    """Proposal from one agent on how to classify the task"""
    agent_id: str
    agent_type: str  # "claude_understander" or "gpt5_understander"
    core_tasks: List[CoreTask]
    side_tasks: List[SideTask]
    execution_order: List[str]  # List of task IDs in order
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    concerns: List[str] = Field(default_factory=list)


class NegotiationMessage(BaseModel):
    """Message during negotiation between agents"""
    from_agent: str
    to_agent: str
    iteration: int
    message_type: str  # "proposal", "critique", "agreement", "disagreement"
    content: str
    disagreements: List[str] = Field(default_factory=list)
    proposed_changes: Optional[Dict[str, Any]] = None
    questions: List[str] = Field(default_factory=list)


class NegotiationResult(BaseModel):
    """Result of negotiation between agents"""
    reached_agreement: bool
    iterations: int
    final_proposal: Optional[TaskClassificationProposal] = None
    disagreements: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class TaskClassification(BaseModel):
    """Final agreed-upon task classification"""
    task_id: str
    core_tasks: List[CoreTask]
    side_tasks: List[SideTask]
    execution_order: List[str]
    agreements: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    negotiation_summary: Optional[str] = None
    timestamp: Optional[str] = None

