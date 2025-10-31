"""
Model Selection Logic for Agent Generator.

Analyzes task complexity and selects the appropriate LLM model.
"""

import re
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class ModelSelector:
    """
    Intelligent model selection based on task complexity ONLY.
    
    NO hardcoded assumptions about task type (coding, database, file operations, etc.)
    The selected model handles ANY type of task at its complexity level.
    
    Model Selection (Domain-Agnostic):
    - Simple tasks    -> GPT-4.1 (fast, versatile)
    - Moderate tasks  -> GPT-4.1 (excellent balance of speed + capability)
    - Complex tasks   -> Claude 4.5 (superior reasoning + code generation)
    
    Available Models:
    - GPT-4o: Fast, cheap (currently unused but available)
    - GPT-4.1: 54.6% SWE-bench, 1M context - best generalist
    - GPT-5 Low/Med/High: Advanced reasoning (available for specific use cases)
    - Claude 4.5: Excellent for complex tasks
    """
    
    # Model definitions
    MODELS = {
        "gpt-4o": {
            "provider": "azure",
            "model_name": "gpt-4o",
            "cost_tier": 1,
            "complexity": ["simple"],
            "reasoning_level": None,
            "note": "Fast, cheap - for simple non-coding tasks only"
        },
        "gpt-4.1": {
            "provider": "azure",
            "model_name": "gpt-4.1",
            "cost_tier": 2,
            "complexity": ["simple", "moderate"],
            "reasoning_level": None,
            "note": "CODING OPTIMIZED - 54.6% SWE-bench, 1M context, best for code generation"
        },
        "gpt-5-low": {
            "provider": "azure",
            "model_name": "gpt-5",
            "cost_tier": 3,
            "complexity": ["simple", "moderate"],
            "reasoning_level": "low",
            "note": "Good reasoning for non-coding tasks"
        },
        "claude-4.5": {
            "provider": "bedrock",
            "model_name": "claude-sonnet-4-5",
            "cost_tier": 4,
            "complexity": ["moderate", "complex"],
            "reasoning_level": None,
            "note": "Excellent for complex coding and reasoning"
        },
        "gpt-5-medium": {
            "provider": "azure",
            "model_name": "gpt-5",
            "cost_tier": 5,
            "complexity": ["complex"],
            "reasoning_level": "medium",
            "note": "Best for complex reasoning tasks"
        },
        "gpt-5-high": {
            "provider": "azure",
            "model_name": "gpt-5",
            "cost_tier": 6,
            "complexity": ["complex", "critical"],
            "reasoning_level": "high",
            "note": "Highest reasoning - critical tasks only"
        }
    }
    
    # Complexity detection patterns (domain-agnostic)
    COMPLEXITY_INDICATORS = {
        "simple": [
            r"\bbasic\b",
            r"\bsimple\b",
            r"\bstraightforward\b",
            r"\bquick\b",
            r"\bcheck\b",
            r"\bverify\b",
        ],
        "moderate": [
            # Multiple step indicators
            r"\bmultiple\b.*\bsteps\b",
            r"\bseveral\b",
            r"\bsequence\b",
            r"\biterative\b",
            r"\bprocess\b",
            r"\btransform\b",
            r"\bvalidate\b",
        ],
        "complex": [
            # Advanced reasoning indicators
            r"\bcomplex\b",
            r"\badvanced\b",
            r"\boptimize\b",
            r"\banalyze\b.*\blogic\b",
            r"\bdynamic\b",
            r"\brecursive\b",
            r"\balgorithm\b",
            r"\bdesign\b",
        ]
    }
    
    @classmethod
    def analyze_complexity(cls, task_description: str, goal: str) -> str:
        """
        Analyze task complexity based on description and goal.
        
        Returns: "simple", "moderate", or "complex"
        """
        combined_text = f"{task_description.lower()} {goal.lower()}"
        
        # Count indicators for each complexity level
        scores = {"simple": 0, "moderate": 0, "complex": 0}
        
        for complexity, patterns in cls.COMPLEXITY_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, combined_text):
                    scores[complexity] += 1
        
        logger.info(f"Complexity scores: {scores}")
        
        # Determine complexity
        # If no indicators found, default to "moderate"
        if sum(scores.values()) == 0:
            return "moderate"
        
        # If complex indicators found, it's complex
        if scores["complex"] > 0:
            return "complex"
        
        # If only simple indicators, it's simple
        if scores["simple"] > 0 and scores["moderate"] == 0:
            return "simple"
        
        # Default to moderate
        return "moderate"
    
    @classmethod
    def select_model(
        cls,
        task_complexity: str,
        preferred_model: str = "auto",
        task_description: str = ""
    ) -> Tuple[str, dict]:
        """
        Select the best model for the task based on complexity.
        
        No hardcoded assumptions about task type (coding vs non-coding).
        Each model is chosen for its overall capability at that complexity level.
        
        Args:
            task_complexity: "simple", "moderate", "complex"
            preferred_model: Specific model or "auto"
            task_description: Reserved for future use (not used for pre-classification)
        
        Returns:
            Tuple of (model_key, model_config)
        """
        # If specific model requested, use it
        if preferred_model != "auto" and preferred_model in cls.MODELS:
            logger.info(f"Using preferred model: {preferred_model}")
            return preferred_model, cls.MODELS[preferred_model]
        
        # Auto-select based on complexity ONLY (no pre-classification of task type)
        # Claude 4.5 is superior for code generation across all complexity levels
        if task_complexity == "simple":
            # Claude 4.5: Excellent code generation, even for simple tasks
            selected = "claude-4.5"
        elif task_complexity == "moderate":
            # Claude 4.5: Superior code generation and reasoning
            selected = "claude-4.5"
        elif task_complexity == "complex":
            # Claude 4.5: Best for complex reasoning and code
            selected = "claude-4.5"
        else:
            # Default to Claude 4.5 (superior code generation)
            selected = "claude-4.5"
        
        logger.info(f"Auto-selected model '{selected}' for complexity '{task_complexity}'")
        return selected, cls.MODELS[selected]
    
    @classmethod
    def get_model_info(cls, model_key: str) -> dict:
        """Get model configuration by key"""
        return cls.MODELS.get(model_key, cls.MODELS["gpt-5-low"])

