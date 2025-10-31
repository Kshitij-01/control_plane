"""
Data models for Phase 0 task classification
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    """Information about a file involved in the task"""
    path: str
    size_mb: Optional[float] = None
    file_type: Optional[str] = None
    description: Optional[str] = None


class ConnectionInfo(BaseModel):
    """Information about a connection (database, API, cluster, etc.)"""
    id: str
    type: str  # postgresql, mysql, databricks, s3, api, etc.
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    workspace_url: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class TaskConstraints(BaseModel):
    """Constraints and requirements for the task"""
    max_duration_hours: Optional[float] = None
    max_cost_usd: Optional[float] = None
    required_resources: Optional[Dict[str, Any]] = None
    dependencies: Optional[List[str]] = None
    priority: Optional[str] = "normal"  # low, normal, high, critical
    deadline: Optional[str] = None

