"""
Bedrock Claude Client for AutoGen

Simple wrapper around AWS Bedrock's Claude models.
"""

import json
from typing import Any, Dict, List, Optional, Sequence, Union

import boto3
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    RequestUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage
)


class BedrockClaudeClient(ChatCompletionClient):
    """
    Chat completion client for AWS Bedrock Claude models.
    Compatible with AutoGen's ChatCompletionClient interface.
    """
    
    def __init__(
        self,
        model_id: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = 'us-east-1',
        max_tokens: int = 4096,
        temperature: float = 0.0,
        enable_thinking: bool = False,
        thinking_budget_tokens: int = 1024
    ):
        """
        Initialize Bedrock Claude client.
        
        Args:
            model_id: Bedrock model ID (e.g., 'anthropic.claude-3-5-sonnet-20241022-v2:0')
            aws_access_key_id: AWS access key
            aws_secret_access_key: AWS secret key
            region_name: AWS region
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            enable_thinking: Enable extended thinking mode (Claude 4.5+)
            thinking_budget_tokens: Tokens allocated for thinking (must be >= 1024)
        """
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._enable_thinking = enable_thinking
        self._thinking_budget_tokens = max(1024, thinking_budget_tokens)  # Ensure minimum 1024
        # CRITICAL: When extended thinking is enabled, temperature MUST be 1.0 per Bedrock API requirements
        self._temperature = 1.0 if enable_thinking else temperature
        
        # Create Bedrock client with increased timeout
        from botocore.config import Config
        config = Config(
            read_timeout=300,  # 5 minutes
            connect_timeout=60,
            retries={'max_attempts': 15}  # Increased retries
        )
        self._client = boto3.client(
            'bedrock-runtime',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
            config=config
        )
    
    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        json_output: Optional[bool] = None,
        extra_create_args: Dict[str, Any] = {},
        cancellation_token: Optional[Any] = None
    ) -> CreateResult:
        """
        Create a chat completion using Bedrock Claude.
        
        Args:
            messages: List of messages in the conversation
            tools: Tool definitions (not used for now)
            json_output: Whether to request JSON output
            extra_create_args: Additional arguments
            cancellation_token: Cancellation token (not used)
        
        Returns:
            CreateResult with the completion
        """
        # Convert messages to Claude format
        system_messages = []
        conversation_messages = []
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_messages.append(msg.content)
            elif isinstance(msg, UserMessage):
                conversation_messages.append({
                    "role": "user",
                    "content": msg.content
                })
            elif isinstance(msg, AssistantMessage):
                conversation_messages.append({
                    "role": "assistant",
                    "content": msg.content
                })
        
        # Build request body
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": conversation_messages
        }
        
        # Add thinking config if enabled (Claude 4.5+)
        if self._enable_thinking:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget_tokens
            }
        
        if system_messages:
            body["system"] = "\n\n".join(system_messages)
        
        # Add JSON mode if requested
        if json_output or extra_create_args.get('response_format') == 'json':
            # For Bedrock, we append to system message to request JSON
            if "system" in body:
                body["system"] += "\n\nYou MUST respond with valid JSON only. Do not include any text before or after the JSON object."
            else:
                body["system"] = "You MUST respond with valid JSON only. Do not include any text before or after the JSON object."
        
        # Invoke Bedrock
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body)
        )
        
        # Parse response
        response_body = json.loads(response['body'].read())
        
        # Extract content - handle extended thinking mode with multiple content blocks
        content_blocks = response_body.get('content', [])
        if content_blocks:
            # When extended thinking is enabled, there may be multiple blocks (thinking + text)
            # Extract all text blocks and concatenate them
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict):
                    block_type = block.get('type', 'text')
                    if block_type == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block_type == 'thinking':
                        # Skip thinking blocks - we only want the actual response
                        continue
            content = '\n'.join(text_parts)
        else:
            content = ''
        
        # Extract usage
        usage_data = response_body.get('usage', {})
        usage = RequestUsage(
            prompt_tokens=usage_data.get('input_tokens', 0),
            completion_tokens=usage_data.get('output_tokens', 0)
        )
        
        # Map Bedrock finish reasons to AutoGen's expected values
        bedrock_reason = response_body.get('stop_reason', 'end_turn')
        finish_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'function_calls'
        }
        finish_reason = finish_reason_map.get(bedrock_reason, 'stop')
        
        return CreateResult(
            finish_reason=finish_reason,
            content=content,
            usage=usage,
            cached=False
        )
    
    @property
    def capabilities(self) -> Dict[str, Any]:
        """Return client capabilities."""
        return {
            "vision": False,
            "function_calling": False,
            "json_output": True
        }
    
    @property
    def model_info(self) -> Dict[str, Any]:
        """Return model information."""
        return {
            "model": self._model_id,
            "provider": "bedrock",
            "max_tokens": self._max_tokens,
            "temperature": self._temperature
        }
    
    def actual_usage(self) -> RequestUsage:
        """Return total usage across all requests."""
        # This would require tracking usage across requests
        return RequestUsage(prompt_tokens=0, completion_tokens=0)
    
    def total_usage(self) -> RequestUsage:
        """Return total usage."""
        return self.actual_usage()
    
    def count_tokens(self, messages: Sequence[LLMMessage]) -> int:
        """Estimate token count for messages."""
        # Simple estimation: ~4 chars per token
        total_chars = sum(len(msg.content) for msg in messages if hasattr(msg, 'content'))
        return total_chars // 4
    
    def remaining_tokens(self, messages: Sequence[LLMMessage]) -> int:
        """Calculate remaining tokens."""
        used = self.count_tokens(messages)
        return self._max_tokens - used
    
    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = [],
        json_output: Optional[bool] = None,
        extra_create_args: Dict[str, Any] = {},
        cancellation_token: Optional[Any] = None
    ):
        """
        Create a streaming chat completion (not implemented for Bedrock).
        Falls back to non-streaming.
        """
        # For now, just use non-streaming
        result = await self.create(
            messages,
            tools=tools,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token
        )
        yield result
    
    async def close(self) -> None:
        """Close the client and cleanup resources."""
        # Bedrock boto3 client doesn't need explicit closing
        pass

