"""
Data models for Phase 1: Core Task Division
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

# Import shared models
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.models import ArtifactRef, OutputContract, ExecutionHints


class Subtask(BaseModel):
    """A subtask within the core task execution"""
    id: str
    description: str
    task_category: str = "independent"  # sequential_first, independent, sequential_last
    dependencies: List[str] = Field(default_factory=list)  # IDs of subtasks that must complete first
    estimated_duration: str = "unknown"
    complexity: str = "moderate"  # simple, moderate, complex
    inputs_required: Dict[str, Any] = Field(default_factory=dict)
    outputs_produced: List[str] = Field(default_factory=list)
    expected_output_files: List[str] = Field(default_factory=list)  # NEW: Contract files - exact filenames
    output_contract: Optional[OutputContract] = None  # NEW: Rich contract specification
    chain_ids: List[int] = Field(default_factory=list)  # For tracking which transformation chains belong to this subtask
    columns_needed: List[str] = Field(default_factory=list)  # Columns this subtask needs (including primary key)
    data_slice: Optional[Dict[str, Any]] = None  # Subset of plan data relevant to this subtask


class TaskDivisionRequest(BaseModel):
    """Request for task division"""
    task_id: str
    core_task_description: str
    plan_file_path: Optional[str] = None  # Path to JSON plan file (mapping, config, etc.)
    plan_content: Optional[Dict[str, Any]] = None  # Or inline plan content
    connections: List[Dict[str, Any]] = Field(default_factory=list)
    additional_context: Dict[str, Any] = Field(default_factory=dict)
    success_criteria: Optional[str] = None


class TaskDivisionResult(BaseModel):
    """Result of task division"""
    task_id: str
    can_be_divided: bool
    reasoning: str
    subtasks: List[Subtask] = Field(default_factory=list)
    execution_strategy: str = "sequential"  # sequential, parallel, dag
    estimated_total_duration: str = "unknown"
    confidence: float = 0.0
    warnings: List[str] = Field(default_factory=list)


class TaskDivisionProposal(BaseModel):
    """Claude's proposal for dividing a task into subtasks"""
    can_be_divided: bool
    reasoning: str
    subtasks: List[Dict[str, Any]] = Field(default_factory=list)  # Will be converted to Subtask objects
    execution_strategy: str = "dag"  # sequential, parallel, dag
    estimated_total_duration: str = "unknown"


class ReviewResult(BaseModel):
    """GPT-5's review of Claude's proposal"""
    satisfied: bool
    confidence: float = 0.0
    feedback: str = ""
    suggestions: List[str] = Field(default_factory=list)
    must_change: List[str] = Field(default_factory=list)


class SubtaskPackage(BaseModel):
    """
    Complete execution package for a single subtask
    Contains everything Phase 2 needs to execute this subtask
    """
    subtask_id: str
    description: str
    task_category: str = "independent"  # sequential_first, independent, sequential_last
    dependencies: List[str] = Field(default_factory=list)
    complexity: str = "moderate"
    estimated_duration: str = "unknown"
    
    # Credentials for all required connections
    credentials: Dict[str, Any] = Field(default_factory=dict)
    
    # Data subset (e.g., only relevant transformation chains)
    data: Dict[str, Any] = Field(default_factory=dict)
    
    # Context and instructions
    task_instructions: str = ""
    success_criteria: str = ""
    
    # Metadata
    columns_needed: List[str] = Field(default_factory=list)  # Columns to extract
    inputs_required: Dict[str, Any] = Field(default_factory=dict)
    outputs_produced: List[str] = Field(default_factory=list)
    
    # OUTPUT CONTRACT (NEW - from Phase 1)
    expected_output_files: List[str] = Field(default_factory=list)  # NEW: Exact filenames required
    output_contract: Optional[OutputContract] = None  # NEW: Rich contract specification
    
    # EXPLICIT I/O FILES (for data flow between tasks)
    input_files: Dict[str, Union[str, List[str]]] = Field(default_factory=dict)  # LEGACY: {dependency_id: filename or list of filenames}
    output_files: List[str] = Field(default_factory=list)  # LEGACY: Files this task creates
    input_artifacts: Dict[str, List[ArtifactRef]] = Field(default_factory=dict)  # NEW: {dependency_id: [artifacts]} - zero-copy refs
    
    # EXECUTION HINTS (passed from manifest through all phases)
    execution_hints: ExecutionHints = Field(default_factory=ExecutionHints)  # NEW: Typed execution hints
    
    # ORCHESTRATOR-PROVIDED PATHS (NEW - resolved by intelligent orchestrator)
    input_file_paths: Optional[List[str]] = None  # Absolute paths to input files (resolved by orchestrator)
    input_file_metadata: Optional[List[Dict[str, Any]]] = None  # Rich metadata for each input file (filename, description, type, source_task)
    execution_guidance: Optional[str] = None  # Brief guidance from orchestrator on what to do

