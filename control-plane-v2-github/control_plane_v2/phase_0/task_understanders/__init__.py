"""
Task Understanders - Agents that analyze and classify tasks

Agent 1a: Claude 4.5 - Technical analysis
Agent 1b: GPT-5 - Logical analysis
"""

from .claude_understander import ClaudeTaskUnderstander
from .gpt5_understander import GPT5TaskUnderstander
from .negotiation import TaskNegotiator
from .overseer import OverseerAgent

__all__ = [
    'ClaudeTaskUnderstander',
    'GPT5TaskUnderstander',
    'TaskNegotiator',
    'OverseerAgent'
]

