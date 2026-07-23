import pytest
import os
import httpx
from src.infrastructure.llm import model_client_factory
from src.infrastructure.llm.model_client_factory import (
    ModelClientFactory,
    DeepSeekClient,
    ZhipuGLMClient,
    AnthropicClaudeClient,
    OpenAIClient,
)


def test_factory_raises_value_error_if_key_missing():
    # Make sure env variables are not present
    old_ds_key = os.environ.pop("DEEPSEEK_API_KEY", None)

    with pytest.raises(ValueError, match="Missing DEEPSEEK_API_KEY"):
        ModelClientFactory.get_client("deepseek")

    if old_ds_key:
        os.environ["DEEPSEEK_API_KEY"] = old_ds_key

def test_factory_returns_correct_client_class():
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    os.environ["GLM_API_KEY"] = "test-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["OPENAI_API_KEY"] = "test-key"

    client = ModelClientFactory.get_client("deepseek")
    assert isinstance(client, DeepSeekClient)

    client = ModelClientFactory.get_client("glm")
    assert isinstance(client, ZhipuGLMClient)

    client = ModelClientFactory.get_client("claude")
    assert isinstance(client, AnthropicClaudeClient)

    client = ModelClientFactory.get_client("openai")
    assert isinstance(client, OpenAIClient)


def test_glm_reads_glm_api_key_not_zhipu_prefixed_name():
    """Regression test: config.py's Settings.GLM_API_KEY, .env.example, and
    docker-compose.yml's x-backend-env anchor all name this credential
    GLM_API_KEY -- ModelClientFactory must consult that same name, not a
    ZHIPU_GLM_API_KEY the rest of the stack never sets."""
    old_key = os.environ.pop("GLM_API_KEY", None)
    os.environ.pop("ZHIPU_GLM_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="Missing GLM_API_KEY"):
            ModelClientFactory.get_client("glm")

        os.environ["ZHIPU_GLM_API_KEY"] = "wrong-name-should-not-be-used"
        with pytest.raises(ValueError, match="Missing GLM_API_KEY"):
            ModelClientFactory.get_client("glm")
    finally:
        os.environ.pop("ZHIPU_GLM_API_KEY", None)
        if old_key:
            os.environ["GLM_API_KEY"] = old_key


# --- generate_stream() tests --------------------------------------------------
#
# Each provider client's generate_stream() opens its own `httpx.AsyncClient()`
# internally, so tests patch `model_client_factory.httpx.AsyncClient` (module-
# level, restored by `monkeypatch` after each test) to inject an
# `httpx.MockTransport` that serves a canned SSE response body -- no real
# network call, no extra test dependency (httpx already ships MockTransport).

_OPENAI_COMPATIBLE_SSE_BODY = (
    b'data: {"id":"x","choices":[{"index":0,"delta":{"role":"assistant","content":""},'
    b'"finish_reason":null}]}\n\n'
    b'data: {"id":"x","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
    b'data: {"id":"x","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}\n\n'
    b'data: {"id":"x","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: [DONE]\n\n'
)

_ANTHROPIC_SSE_BODY = (
    b'event: message_start\n'
    b'data: {"type":"message_start","message":{"id":"msg_1","content":[],"model":"claude-3-5-sonnet-latest"}}\n\n'
    b'event: content_block_start\n'
    b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
    b'event: ping\n'
    b'data: {"type":"ping"}\n\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
    b'event: content_block_delta\n'
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"!"}}\n\n'
    b'event: content_block_stop\n'
    b'data: {"type":"content_block_stop","index":0}\n\n'
    b'event: message_delta\n'
    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},'
    b'"usage":{"output_tokens":2}}\n\n'
    b'event: message_stop\n'
    b'data: {"type":"message_stop"}\n\n'
)


# Captured before any test patches `model_client_factory.httpx.AsyncClient` --
# `model_client_factory.httpx` *is* the same `httpx` module object imported
# here, so patching its `AsyncClient` attribute patches it everywhere `httpx`
# is imported. The fake factory below must construct real client instances
# via this pre-patch reference, or it recurses into itself infinitely.
_RealAsyncClient = httpx.AsyncClient


def _mock_async_client(monkeypatch, response_body: bytes, status_code: int = 200):
    """Patch `model_client_factory.httpx.AsyncClient` so every provider client's
    internal `httpx.AsyncClient(...)` call is transparently backed by an
    `httpx.MockTransport` returning `response_body`/`status_code` for any request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=response_body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)

    def fake_async_client(*args, **kwargs):
        return _RealAsyncClient(transport=transport)

    monkeypatch.setattr(model_client_factory.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_deepseek_generate_stream_yields_text_chunks(monkeypatch):
    _mock_async_client(monkeypatch, _OPENAI_COMPATIBLE_SSE_BODY)
    client = DeepSeekClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_glm_generate_stream_yields_text_chunks(monkeypatch):
    _mock_async_client(monkeypatch, _OPENAI_COMPATIBLE_SSE_BODY)
    client = ZhipuGLMClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_openai_generate_stream_yields_text_chunks(monkeypatch):
    _mock_async_client(monkeypatch, _OPENAI_COMPATIBLE_SSE_BODY)
    client = OpenAIClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_anthropic_generate_stream_yields_text_deltas_only(monkeypatch):
    _mock_async_client(monkeypatch, _ANTHROPIC_SSE_BODY)
    client = AnthropicClaudeClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    # Only content_block_delta/text_delta frames should surface as text;
    # message_start/ping/content_block_start-stop/message_delta/message_stop
    # are control frames and must be ignored.
    assert chunks == ["Hello", "!"]


@pytest.mark.asyncio
async def test_generate_stream_empty_body_yields_nothing(monkeypatch):
    _mock_async_client(monkeypatch, b"")
    client = DeepSeekClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    assert chunks == []


@pytest.mark.asyncio
async def test_generate_stream_skips_malformed_json_chunk(monkeypatch):
    body = (
        b"data: not-json\n\n"
        b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )
    _mock_async_client(monkeypatch, body)
    client = OpenAIClient("test-key")

    chunks = [chunk async for chunk in client.generate_stream("prompt", "system")]

    assert chunks == ["ok"]


@pytest.mark.asyncio
async def test_generate_stream_raises_on_http_error_status(monkeypatch):
    _mock_async_client(monkeypatch, b'{"error": "unauthorized"}', status_code=401)
    client = DeepSeekClient("bad-key")

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in client.generate_stream("prompt", "system"):
            pass
