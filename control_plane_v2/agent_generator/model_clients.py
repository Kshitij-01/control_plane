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
from control_plane_v2.azure_anthropic_client import AzureAnthropicClient


def create_all_model_clients(env_config: dict) -> Dict[str, ChatCompletionClient]:
    """
    Create all available model clients from environment configuration.
    
    Returns dict with keys: gpt-4o, gpt-4.1, gpt-5-low, gpt-5-medium, gpt-5-high, claude-4.5
    """
    clients = {}
    
    azure_config = env_config['llm_config']['azure']
    bedrock_config = env_config['llm_config'].get('bedrock') or {}
    # Optional: use a different endpoint for chat (e.g. where GPT deployments exist)
    chat_endpoint = azure_config.get('chat_endpoint') or azure_config['endpoint']
    chat_api_key = azure_config.get('chat_api_key') or azure_config['api_key']

    # GPT-4o (fast, cheap)
    gpt4o_model = azure_config.get('gpt4o_deployment') or azure_config.get('gpt4o_model', 'gpt-4o')
    try:
        clients['gpt-4o'] = AzureOpenAIChatCompletionClient(
            model=gpt4o_model,
            api_version=azure_config['api_version'],
            azure_endpoint=chat_endpoint,
            api_key=chat_api_key,
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
    gpt41_model = azure_config.get('gpt41_deployment') or azure_config.get('gpt41_model', 'gpt-4.1')
    try:
        clients['gpt-4.1'] = AzureOpenAIChatCompletionClient(
            model=gpt41_model,
            api_version=azure_config['api_version'],
            azure_endpoint=chat_endpoint,
            api_key=chat_api_key,
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
    gpt5_model = azure_config.get('gpt5_deployment') or azure_config.get('gpt5_model')
    clients['gpt-5-low'] = AzureOpenAIChatCompletionClient(
        model=gpt5_model,
        api_version=azure_config['api_version'],
        azure_endpoint=chat_endpoint,
        api_key=chat_api_key,
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
        model=gpt5_model,
        api_version=azure_config['api_version'],
        azure_endpoint=chat_endpoint,
        api_key=chat_api_key,
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
        model=gpt5_model,
        api_version=azure_config['api_version'],
        azure_endpoint=chat_endpoint,
        api_key=chat_api_key,
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
    
    # Claude 4.5: prefer Azure Anthropic Sonnet, then Azure OpenAI Claude, then Bedrock, then GPT fallback
    use_azure_for_claude = azure_config.get('claude_deployment') or azure_config.get('use_azure_for_claude', False)
    anthropic_azure = env_config.get('llm_config', {}).get('anthropic_azure') or {}

    # 1) Azure Anthropic (Sonnet) - Anthropic Messages API at Azure endpoint (not OpenAI-compatible)
    if (use_azure_for_claude or anthropic_azure) and anthropic_azure.get('sonnet_deployment') and anthropic_azure.get('endpoint') and anthropic_azure.get('api_key'):
        try:
            base_url = anthropic_azure['endpoint'].rstrip('/')
            clients['claude-4.5'] = AzureAnthropicClient(
                base_url=base_url,
                api_key=anthropic_azure['api_key'],
                model=anthropic_azure['sonnet_deployment'],
                max_tokens=anthropic_azure.get('max_tokens', 8192),
                temperature=anthropic_azure.get('temperature_coder', 0.0),
            )
            print("[INFO] Claude 4.5 client configured via Azure Anthropic (Sonnet, Messages API)")
        except Exception as e:
            print(f"Warning: Could not create Azure Anthropic Sonnet client: {e}")

    # 2) Azure OpenAI Claude deployment (if present on main azure config)
    if 'claude-4.5' not in clients and use_azure_for_claude and azure_config.get('claude_deployment'):
        try:
            clients['claude-4.5'] = AzureOpenAIChatCompletionClient(
                model=azure_config['claude_deployment'],
                api_version=azure_config['api_version'],
                azure_endpoint=azure_config['endpoint'],
                api_key=azure_config['api_key'],
                model_capabilities={
                    "reasoning": True,
                    "vision": False,
                    "function_calling": True,
                    "json_output": True,
                    "coding": True
                }
            )
            print("[INFO] Claude 4.5 client configured via Azure OpenAI")
        except Exception as e:
            print(f"Warning: Could not create Azure Claude client: {e}")

    if 'claude-4.5' not in clients:
        # 3) Fallback: use Azure GPT (no 4o; prefer GPT-5 then gpt-4.1) when use_azure_for_claude
        if azure_config.get('use_azure_for_claude', False):
            fallback = clients.get('gpt-5') or clients.get('gpt-5-medium') or clients.get('gpt-4.1')
            if fallback:
                clients['claude-4.5'] = fallback
                print("[INFO] Claude role using Azure fallback (GPT-5 / gpt-4.1) - no Sonnet")
        # 4) Bedrock Claude (optional)
        if 'claude-4.5' not in clients and bedrock_config.get('claude_4_5_model_id') and bedrock_config.get('aws_access_key_id') and not azure_config.get('use_azure_for_claude'):
            try:
                clients['claude-4.5'] = BedrockClaudeClient(
                    model_id=bedrock_config['claude_4_5_model_id'],
                    aws_access_key_id=bedrock_config['aws_access_key_id'],
                    aws_secret_access_key=bedrock_config['aws_secret_access_key'],
                    region_name=bedrock_config.get('region', 'us-east-1'),
                    max_tokens=bedrock_config.get('max_tokens', 8192),
                    temperature=bedrock_config.get('temperature_coder', 0.2),
                    enable_thinking=bedrock_config.get('enable_thinking_mode', False),
                    thinking_budget_tokens=bedrock_config.get('thinking_budget_tokens', 1024)
                )
                print("[INFO] Claude 4.5 client configured via AWS Bedrock")
            except Exception as e:
                print(f"Warning: Could not create Bedrock Claude client: {e}")
        # 5) Last resort: GPT-5 or gpt-4.1 (no 4o)
        if 'claude-4.5' not in clients:
            fallback = clients.get('gpt-5') or clients.get('gpt-4.1')
            if fallback:
                clients['claude-4.5'] = fallback
                print("[INFO] Claude role using Azure fallback (GPT-5 / gpt-4.1) - Bedrock not available")
    
    # Add convenient aliases
    clients['gpt-5'] = clients['gpt-5-medium']  # Default GPT-5 = medium reasoning
    
    return clients

