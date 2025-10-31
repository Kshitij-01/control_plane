"""
Shared Pydantic models for the entire control plane.
These models ensure type safety and validation across all phases.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ArtifactRef(BaseModel):
    """
    Reference to a file artifact in the system.
    Used for zero-copy data flow - pass references, not copies.
    """
    id: str = Field(..., description="Unique identifier (hash-based: sha256:...)")
    logical_name: str = Field(..., description="Logical name (e.g., 'batch_1', 'analysis')")
    filename: str = Field(..., description="Exact filename with extension")
    path: str = Field(..., description="Absolute file path")
    file_type: Literal["data", "metadata", "log", "temp", "intermediate", "output"] = "data"
    mime_type: Optional[str] = Field(None, description="MIME type (e.g., 'text/csv')")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
    sha256: Optional[str] = Field(None, description="SHA256 hash for integrity")
    produced_by_task: Optional[str] = Field(None, description="Task ID that created this artifact")
    created_at: Optional[str] = Field(None, description="ISO timestamp")


class OutputContract(BaseModel):
    """
    Contract specifying expected output files from a task.
    More sophisticated than just a list of filenames.
    """
    required_files: List[str] = Field(default_factory=list, description="Exact filenames required (e.g., ['batch_1.csv'])")
    optional_files: List[str] = Field(default_factory=list, description="Optional output files")
    roles: Dict[str, str] = Field(default_factory=dict, description="Logical name -> filename mapping")
    flexible_extension: bool = Field(False, description="If true, allow different extensions (.csv, .parquet, etc.)")
    min_file_size: Optional[int] = Field(None, description="Minimum expected file size in bytes")


class ExecutionHints(BaseModel):
    """
    Hints for how to execute a task.
    Controls behavior like data copying, materialization, etc.
    """
    materialize_mode: Literal["none", "link", "copy"] = Field(
        "none",
        description="How to handle input files: none=use refs only, link=hardlink, copy=full copy"
    )
    enable_parallel: bool = Field(True, description="Allow parallel execution if possible")
    timeout_seconds: Optional[int] = Field(None, description="Max execution time")
    retry_on_failure: bool = Field(True, description="Retry on failure")
    max_retries: int = Field(3, description="Max retry attempts")


class TaskMetrics(BaseModel):
    """
    Metrics collected during task execution.
    """
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    attempts: int = 1
    success: bool = False
    files_created_count: int = 0
    total_output_bytes: int = 0

