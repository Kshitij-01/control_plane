"""
Bedrock Claude Client for AutoGen

Simple wrapper around AWS Bedrock's Claude models.
Supports PDF processing via Claude Sonnet 4.5+
"""

import asyncio
import json
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import boto3
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    RequestUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    FunctionExecutionResultMessage
)
from autogen_core._types import FunctionCall


class PDFDocument:
    """Represents a PDF document for Claude processing"""
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            self.pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        self.file_size_mb = len(pdf_bytes) / (1024 * 1024)
        
        if self.file_size_mb > 32:
            raise ValueError(f"PDF file too large: {self.file_size_mb:.1f}MB (max 32MB)")
    
    def to_bedrock_content(self) -> dict:
        """Convert to Bedrock API format"""
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": self.pdf_base64
            }
        }


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
                # Handle PDF documents in user messages
                content = msg.content
                
                # Check if content is a list (multimodal content)
                if isinstance(content, list):
                    # Content is already structured (e.g., [{"type": "document", ...}, {"type": "text", ...}])
                    conversation_messages.append({
                        "role": "user",
                        "content": content
                    })
                else:
                    # Regular text message
                    conversation_messages.append({
                        "role": "user",
                        "content": content
                    })
            elif isinstance(msg, AssistantMessage):
                # Handle assistant messages with tool calls
                if isinstance(msg.content, list) and all(isinstance(item, FunctionCall) for item in msg.content):
                    # Convert FunctionCall objects to Claude format
                    content_blocks = []
                    for call in msg.content:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": json.loads(call.arguments)
                        })
                    conversation_messages.append({
                        "role": "assistant",
                        "content": content_blocks
                    })
                else:
                    conversation_messages.append({
                        "role": "assistant",
                        "content": msg.content
                    })
            elif isinstance(msg, FunctionExecutionResultMessage):
                # Convert tool results to Claude format
                tool_results = []
                for result in msg.content:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": result.call_id,
                        "content": result.content
                    })
                conversation_messages.append({
                    "role": "user",
                    "content": tool_results
                })
        
        # Build request body
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": conversation_messages
        }
        
        # Add thinking config if enabled (Claude 4.5+)
        # NOTE: Disable thinking when tools are present to avoid conflicts
        if self._enable_thinking and not tools:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget_tokens
            }
        
        if system_messages:
            body["system"] = "\n\n".join(system_messages)
        
        # Add tools if provided
        if tools:
            # Convert AutoGen FunctionTool schemas to Claude format
            claude_tools = []
            for tool in tools:
                if hasattr(tool, 'schema'):
                    # FunctionTool has a schema attribute with the correct format
                    schema = tool.schema
                    claude_tools.append({
                        "name": schema.get("name", tool.name),
                        "description": schema.get("description", tool.description),
                        "input_schema": schema.get("parameters", {
                            "type": "object",
                            "properties": {},
                            "required": []
                        })
                    })
            
            if claude_tools:
                body["tools"] = claude_tools
        
        # Add JSON mode if requested
        if json_output or extra_create_args.get('response_format') == 'json':
            # For Bedrock, we append to system message to request JSON
            if "system" in body:
                body["system"] += "\n\nYou MUST respond with valid JSON only. Do not include any text before or after the JSON object."
            else:
                body["system"] = "You MUST respond with valid JSON only. Do not include any text before or after the JSON object."
        
        # Log before making API call
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[BEDROCK] Calling Claude API - Model: {self._model_id}, Messages: {len(conversation_messages)}, Tools: {len(tools) if tools else 0}")
        
        # Invoke Bedrock with error handling
        try:
            # Define sync function to run in thread pool
            def _invoke_bedrock_sync():
                return self._client.invoke_model(
                    modelId=self._model_id,
                    body=json.dumps(body)
                )
            
            # Run synchronous boto3 call in thread pool (enables parallelism)
            response = await asyncio.to_thread(_invoke_bedrock_sync)
            
            # Parse response
            response_body = json.loads(response['body'].read())
            logger.info(f"[BEDROCK] Received response - Stop reason: {response_body.get('stop_reason', 'unknown')}")
            
        except Exception as e:
            logger.error(f"[BEDROCK_ERROR] Bedrock API call failed: {type(e).__name__}: {str(e)}")
            logger.error(f"[BEDROCK_ERROR] Model: {self._model_id}")
            logger.error(f"[BEDROCK_ERROR] Message count: {len(conversation_messages)}")
            logger.error(f"[BEDROCK_ERROR] Has tools: {bool(tools)}")
            
            # Raise a more descriptive error
            raise RuntimeError(
                f"Bedrock Claude API call failed: {type(e).__name__}: {str(e)}. "
                f"Model: {self._model_id}, Messages: {len(conversation_messages)}"
            ) from e
        
        # Extract content - handle extended thinking mode and tool calls
        content_blocks = response_body.get('content', [])
        content = None
        tool_calls = []
        
        if content_blocks:
            # When extended thinking is enabled, there may be multiple blocks (thinking + text + tool_use)
            # Extract all text blocks and tool calls
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict):
                    block_type = block.get('type', 'text')
                    if block_type == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block_type == 'thinking':
                        # Skip thinking blocks - we only want the actual response
                        continue
                    elif block_type == 'tool_use':
                        # Handle tool calls - block itself contains the tool info
                        # Claude returns: {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
                        tool_calls.append(FunctionCall(
                            id=block.get('id', ''),
                            name=block.get('name', ''),
                            arguments=json.dumps(block.get('input', {}))
                        ))
            
            # Debug logging before deciding content
            logger.info(f"[BEDROCK] text_parts: {len(text_parts)}, tool_calls: {len(tool_calls)}")
            if text_parts:
                logger.info(f"[BEDROCK] text_parts content: {text_parts[0][:100] if text_parts else 'N/A'}...")
            
            # CRITICAL: If there are tool calls, ALWAYS return them (even if there's also text)
            # Claude often writes explanatory text BEFORE tool calls - we want the tool calls!
            if tool_calls:
                content = tool_calls
                logger.info(f"[BEDROCK] Returning {len(tool_calls)} tool calls as content (ignoring text)")
            elif text_parts:
                # Only return text if there are NO tool calls
                content = '\n'.join(text_parts)
                logger.info(f"[BEDROCK] Returning text content (no tool calls)")
        else:
            content = ''
        
        # Debug logging for content type
        logger.info(f"[BEDROCK] Final content type: {type(content).__name__}, Is list: {isinstance(content, list)}")
        
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
            "function_calling": True,
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

