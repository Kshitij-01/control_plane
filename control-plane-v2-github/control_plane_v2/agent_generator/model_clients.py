"""
Model Client Factory

Creates LLM clients for different models based on env_info.json configuration.
"""

import json
from pathlib import Path
from typing import Dict

from autogen_core.models import ChatCompletionClient
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from control_plane_v2.bedrock_client import BedrockClaudeClient


def create_all_model_clients(env_config: dict) -> Dict[str, ChatCompletionClient]:
    """
    Create all available model clients from environment configuration.
    
    Returns dict with keys: gpt-4o, gpt-4.1, gpt-5-low, gpt-5-medium, gpt-5-high, claude-4.5
    """
    clients = {}
    
    azure_config = env_config['llm_config']['azure']
    bedrock_config = env_config['llm_config']['bedrock']
    
    # GPT-4o (fast, cheap)
    try:
        clients['gpt-4o'] = AzureOpenAIChatCompletionClient(
            model="gpt-4o",
            api_version=azure_config['api_version'],
            azure_endpoint=azure_config['endpoint'],
            api_key=azure_config['api_key'],
            model_capabilities={
                "reasoning": False,
                "vision": True,
                "function_calling": True,
                "json_output": True
            }
        )
    except Exception as e:
        print(f"Warning: Could not create GPT-4o client: {e}")
    
    # GPT-4.1 (coding-optimized model, released April 2025)
    try:
        clients['gpt-4.1'] = AzureOpenAIChatCompletionClient(
            model="gpt-4.1",  # Real model deployment in Azure
            api_version=azure_config['api_version'],
            azure_endpoint=azure_config['endpoint'],
            api_key=azure_config['api_key'],
            model_capabilities={
                "reasoning": True,
                "vision": False,
                "function_calling": True,
                "json_output": True,
                "coding": True  # Optimized for coding
            }
        )
        print("[INFO] GPT-4.1 client configured (coding-optimized model)")
    except Exception as e:
        print(f"Warning: Could not create GPT-4.1 client: {e}")
    
    # GPT-5 Low Reasoning
    clients['gpt-5-low'] = AzureOpenAIChatCompletionClient(
        model=azure_config['gpt5_model'],
        api_version=azure_config['api_version'],
        azure_endpoint=azure_config['endpoint'],
        api_key=azure_config['api_key'],
        model_capabilities={
            "reasoning": True,
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True
        },
        model_kwargs={
            "reasoning_level": "low"
        }
    )
    
    # GPT-5 Medium Reasoning (elevated to high for critical planning tasks)
    clients['gpt-5-medium'] = AzureOpenAIChatCompletionClient(
        model=azure_config['gpt5_model'],
        api_version=azure_config['api_version'],
        azure_endpoint=azure_config['endpoint'],
        api_key=azure_config['api_key'],
        model_capabilities={
            "reasoning": True,
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True
        },
        model_kwargs={
            "reasoning_level": "high"
        }
    )
    
    # GPT-5 High Reasoning
    clients['gpt-5-high'] = AzureOpenAIChatCompletionClient(
        model=azure_config['gpt5_model'],
        api_version=azure_config['api_version'],
        azure_endpoint=azure_config['endpoint'],
        api_key=azure_config['api_key'],
        model_capabilities={
            "reasoning": True,
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True
        },
        model_kwargs={
            "reasoning_level": "high"
        }
    )
    
    # Claude 4.5 Sonnet (Bedrock) with Extended Thinking Mode
    clients['claude-4.5'] = BedrockClaudeClient(
        model_id=bedrock_config['claude_4_5_model_id'],
        aws_access_key_id=bedrock_config['aws_access_key_id'],
        aws_secret_access_key=bedrock_config['aws_secret_access_key'],
        region_name=bedrock_config['region'],
        max_tokens=bedrock_config['max_tokens'],
        temperature=bedrock_config['temperature_coder'],
        enable_thinking=bedrock_config.get('enable_thinking_mode', False),
        thinking_budget_tokens=bedrock_config.get('thinking_budget_tokens', 1024)
    )
    
    # Add convenient aliases
    clients['gpt-5'] = clients['gpt-5-medium']  # Default GPT-5 = medium reasoning
    
    return clients

