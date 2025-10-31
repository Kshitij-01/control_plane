"""
Agent Generator Package

Implements dynamic agent generation using AutoGen Core patterns.
"""

from .messages import (
    AgentGenerationRequest,
    AgentGenerationResult,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentCleanupRequest,
    AgentCleanupResult,
)

from .generator import AgentGeneratorAgent
from .executor import GeneratedAgentExecutor
from .factory import AgentFactory
from .verifier import TaskVerifier

__all__ = [
    # Messages
    "AgentGenerationRequest",
    "AgentGenerationResult",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentCleanupRequest",
    "AgentCleanupResult",
    # Agents
    "AgentGeneratorAgent",
    "GeneratedAgentExecutor",
    "TaskVerifier",
    # Factory
    "AgentFactory",
]
