import json
import os
from typing import Any, AsyncGenerator, Dict, Optional

import httpx

from src.domain.ports.model_provider import ModelProviderPort


async def _stream_openai_compatible_sse(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> AsyncGenerator[str, None]:
    """Shared SSE parser for the OpenAI-compatible `chat/completions` streaming
    wire format used (identically) by DeepSeek, Zhipu GLM and OpenAI itself:

        data: {"choices": [{"delta": {"content": "..."}, "finish_reason": null}]}\n\n
        ...
        data: [DONE]\n\n

    Verified against current provider docs via Context7:
    - OpenAI: https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events
    - DeepSeek: https://api-docs.deepseek.com/api/create-chat-completion (OpenAI-compatible,
      terminated by a literal `data: [DONE]` line).
    - Zhipu/GLM (bigmodel.cn): https://docs.bigmodel.cn/cn/guide/capabilities/streaming
      (same `choices[0].delta.content` shape, `Authorization: Bearer` auth, terminated
      by `data: [DONE]`).

    Each `choices[0].delta.content` fragment is yielded as soon as it arrives.
    Malformed/empty lines are skipped rather than raised, so a partial or
    slightly-off-spec chunk never aborts the whole stream early.
    """
    async with client.stream("POST", url, json=payload, headers=headers) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str:
                continue
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                # Malformed chunk: skip it rather than crashing the whole stream.
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


async def _stream_anthropic_sse(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> AsyncGenerator[str, None]:
    """SSE parser for Anthropic's Messages API streaming format, which differs
    from the OpenAI-compatible shape: events are named (`event: <type>`) and
    only `content_block_delta` events whose `delta.type == "text_delta"` carry
    user-visible text.

    Verified against current Anthropic docs via Context7
    (https://platform.claude.com/docs/en/build-with-claude/streaming), which
    documents the exact frame sequence:

        event: message_start
        data: {"type": "message_start", "message": {...}}

        event: content_block_start
        data: {"type": "content_block_start", "index": 0, "content_block": {...}}

        event: ping
        data: {"type": "ping"}

        event: content_block_delta
        data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}

        event: content_block_stop
        data: {"type": "content_block_stop", "index": 0}

        event: message_delta
        data: {"type": "message_delta", "delta": {"stop_reason": "end_turn", ...}, "usage": {...}}

        event: message_stop
        data: {"type": "message_stop"}

    Only `content_block_delta` / `text_delta` frames yield text; `message_start`,
    `ping`, `content_block_start/stop`, `message_delta` and `message_stop` are
    control frames with no user-visible content and are ignored. An `error`
    event (if the API sends one mid-stream) ends the generator cleanly instead
    of raising.
    """
    async with client.stream("POST", url, json=payload, headers=headers) as response:
        response.raise_for_status()
        event_type: Optional[str] = None
        async for line in response.aiter_lines():
            if not line:
                # Blank line = end of one SSE frame; reset for the next one.
                event_type = None
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
                continue
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if event_type == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if text:
                        yield text
            elif event_type == "error":
                # Provider-side stream error: stop cleanly, don't propagate.
                return
            elif event_type == "message_stop":
                return


class DeepSeekClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async for token in _stream_openai_compatible_sse(
                client, f"{self.base_url}/chat/completions", payload, headers
            ):
                yield token


class ZhipuGLMClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://open.bigmodel.cn/api/paas/v4"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "glm-4",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "glm-4",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async for token in _stream_openai_compatible_sse(
                client, f"{self.base_url}/chat/completions", payload, headers
            ):
                yield token


class AnthropicClaudeClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> AsyncGenerator[str, None]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async for token in _stream_anthropic_sse(
                client, f"{self.base_url}/messages", payload, headers
            ):
                yield token


class OpenAIClient(ModelProviderPort):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> AsyncGenerator[str, None]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async for token in _stream_openai_compatible_sse(
                client, f"{self.base_url}/chat/completions", payload, headers
            ):
                yield token


class ModelClientFactory:
    """
    Factory to construct BYOK clients based on model availability.
    """

    @staticmethod
    def get_client(provider_name: str) -> ModelProviderPort:
        provider_name = provider_name.lower()

        if provider_name == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("Missing DEEPSEEK_API_KEY in environment variables.")
            return DeepSeekClient(api_key)

        elif provider_name in ["glm", "z.ai", "zhipu"]:
            # NOT "ZHIPU_GLM_API_KEY" -- config.py's Settings.GLM_API_KEY,
            # .env.example, and docker-compose.yml's x-backend-env anchor
            # (the only thing that injects real env vars into the
            # backend/worker containers) all use "GLM_API_KEY". A name
            # mismatch here previously meant an operator following
            # .env.example exactly still got a 400 on every glm/z.ai/zhipu
            # request, unauthenticated env var never actually set.
            api_key = os.getenv("GLM_API_KEY")
            if not api_key:
                raise ValueError("Missing GLM_API_KEY in environment variables.")
            return ZhipuGLMClient(api_key)

        elif provider_name in ["claude", "anthropic"]:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("Missing ANTHROPIC_API_KEY in environment variables.")
            return AnthropicClaudeClient(api_key)

        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("Missing OPENAI_API_KEY in environment variables.")
            return OpenAIClient(api_key)

        else:
            raise ValueError(f"Unsupported model provider: {provider_name}")
