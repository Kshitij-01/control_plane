"""
Message types for Agent Generator system.

Following AutoGen Core best practices:
- Use Pydantic models for type safety
- Clear message protocols
- Structured data exchange
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime


class AgentGenerationRequest(BaseModel):
    """Request to generate a specialized agent"""
    request_id: str = Field(description="Unique request identifier")
    task_description: str = Field(description="What the agent should do")
    goal: str = Field(description="Specific objective to accomplish")
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context data (credentials, hosts, parameters)"
    )
    success_criteria: str = Field(
        description="How to determine task completion"
    )
    max_iterations: int = Field(
        default=10,
        description="Maximum code execution rounds"
    )
    timeout_seconds: int = Field(
        default=300,
        description="Maximum execution time"
    )
    work_dir: Optional[str] = Field(
        default=None,
        description="Working directory for code execution"
    )
    task_complexity: Optional[str] = Field(
        default="auto",
        description="Task complexity: 'simple', 'moderate', 'complex', or 'auto' for automatic detection"
    )
    preferred_model: Optional[str] = Field(
        default="auto",
        description="Preferred model: 'gpt-4o', 'gpt-4-turbo', 'gpt-5-low', 'gpt-5-medium', 'gpt-5-high', 'claude-4.5', or 'auto'"
    )
    tools: Optional[List[Any]] = Field(
        default=None,
        description="Optional list of FunctionTool objects for the agent to use"
    )


class AgentGenerationResult(BaseModel):
    """Result of agent generation"""
    request_id: str
    agent_id: str = Field(description="Generated agent identifier")
    status: str = Field(description="success or failure")
    system_prompt: str = Field(description="System prompt used for agent")
    selected_model: str = Field(description="Model selected for this agent")
    task_complexity: str = Field(description="Detected or specified task complexity")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    created_at: datetime = Field(default_factory=datetime.now)


class AgentExecutionRequest(BaseModel):
    """Request to execute a generated agent"""
    agent_id: str = Field(description="Agent to execute")
    message: str = Field(description="Instruction message for agent")


class AgentExecutionResult(BaseModel):
    """Result of agent execution"""
    agent_id: str
    status: str = Field(description="completed, failed, or timeout")
    output: str = Field(description="Agent's output/result")
    iterations: int = Field(description="Number of code execution rounds")
    duration_seconds: float = Field(description="Total execution time")
    error: Optional[str] = Field(default=None, description="Error if failed")
    artifacts: List[str] = Field(
        default_factory=list,
        description="Files generated during execution"
    )


class AgentCleanupRequest(BaseModel):
    """Request to cleanup a generated agent"""
    agent_id: str = Field(description="Agent to cleanup")


class AgentCleanupResult(BaseModel):
    """Result of agent cleanup"""
    agent_id: str
    status: str = Field(description="cleaned or failed")
    files_removed: int = Field(default=0, description="Number of files deleted")
    error: Optional[str] = Field(default=None)
