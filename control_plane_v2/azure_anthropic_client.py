"""
Azure Anthropic Client for AutoGen

Calls Azure-hosted Claude via the Anthropic Messages API (POST /v1/messages).
Use when env_info has llm_config.anthropic_azure with endpoint and sonnet_deployment.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    RequestUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    FunctionExecutionResultMessage,
)
from autogen_core._types import FunctionCall

logger = logging.getLogger(__name__)


class AzureAnthropicClient(ChatCompletionClient):
    """
    Chat completion client for Azure-hosted Claude (Anthropic Messages API).
    Compatible with AutoGen's ChatCompletionClient interface.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def _messages_to_body(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[Any] = (),
        json_output: bool = False,
    ) -> Dict[str, Any]:
        system_parts = []
        conversation = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_parts.append(msg.content)
            elif isinstance(msg, UserMessage):
                content = msg.content
                if isinstance(content, list):
                    conversation.append({"role": "user", "content": content})
                else:
                    conversation.append({"role": "user", "content": content})
            elif isinstance(msg, AssistantMessage):
                if isinstance(msg.content, list) and all(
                    isinstance(item, FunctionCall) for item in msg.content
                ):
                    blocks = []
                    for call in msg.content:
                        blocks.append({
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": json.loads(call.arguments),
                        })
                    conversation.append({"role": "assistant", "content": blocks})
                else:
                    conversation.append({"role": "assistant", "content": msg.content})
            elif isinstance(msg, FunctionExecutionResultMessage):
                results = []
                for r in msg.content:
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": r.call_id,
                        "content": r.content,
                    })
                conversation.append({"role": "user", "content": results})

        body = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": conversation,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if tools:
            claude_tools = []
            for t in tools:
                schema = getattr(t, "schema", None) or {}
                claude_tools.append({
                    "name": schema.get("name", getattr(t, "name", "tool")),
                    "description": schema.get("description", getattr(t, "description", "")),
                    "input_schema": schema.get("parameters", {"type": "object", "properties": {}, "required": []}),
                })
            if claude_tools:
                body["tools"] = claude_tools
        if json_output:
            if "system" in body:
                body["system"] += "\n\nRespond with valid JSON only."
            else:
                body["system"] = "Respond with valid JSON only."
        return body

    def _sync_post(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            raise RuntimeError(f"Azure Anthropic API call failed: {e}") from e

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        json_output: Optional[bool] = None,
        extra_create_args: Dict[str, Any] = {},
        cancellation_token: Optional[Any] = None,
    ) -> CreateResult:
        body = self._messages_to_body(
            messages,
            tools=tools,
            json_output=json_output or extra_create_args.get("response_format") == "json",
        )
        url = f"{self._base_url}/v1/messages"
        if not url.startswith("https://") and not url.startswith("http://"):
            url = "https://" + url.lstrip("/")
        logger.info(f"[AZURE_ANTHROPIC] POST {url} model={self._model} messages={len(body.get('messages', []))}")
        try:
            response_body = await asyncio.to_thread(self._sync_post, url, body)
        except Exception as e:
            logger.error(f"[AZURE_ANTHROPIC] Request failed: {e}")
            raise

        content_blocks = response_body.get("content", [])
        content = None
        tool_calls = []
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict):
                t = block.get("type", "text")
                if t == "text":
                    text_parts.append(block.get("text", ""))
                elif t == "thinking":
                    continue
                elif t == "tool_use":
                    tool_calls.append(FunctionCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {})),
                    ))
        if tool_calls:
            content = tool_calls
        elif text_parts:
            content = "\n".join(text_parts)
        else:
            content = ""

        usage_data = response_body.get("usage", {})
        usage = RequestUsage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
        )
        stop_reason = response_body.get("stop_reason", "end_turn")
        finish_reason = "function_calls" if stop_reason == "tool_use" else "stop" if stop_reason == "end_turn" else "length"
        return CreateResult(finish_reason=finish_reason, content=content, usage=usage, cached=False)

    @property
    def capabilities(self) -> Dict[str, Any]:
        return {
            "reasoning": True,
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "coding": True,
        }

    @property
    def model_info(self) -> Dict[str, Any]:
        return {
            "model": self._model,
            "provider": "azure_anthropic",
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

    def actual_usage(self) -> RequestUsage:
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def total_usage(self) -> RequestUsage:
        return self.actual_usage()

    def count_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()) -> int:
        total = 0
        for msg in messages:
            c = getattr(msg, "content", None)
            if isinstance(c, str):
                total += len(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and "text" in block:
                        total += len(block["text"])
        return max(0, total // 4)

    def remaining_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Any] = ()) -> int:
        return max(0, self._max_tokens - self.count_tokens(messages, tools=tools))

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Any] = (),
        json_output: Optional[bool] = None,
        extra_create_args: Dict[str, Any] = {},
        cancellation_token: Optional[Any] = None,
    ):
        result = await self.create(
            messages,
            tools=tools,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )
        yield result

    async def close(self) -> None:
        pass
