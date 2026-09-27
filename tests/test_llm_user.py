"""The OpenAI `user` field: it is only sent when AI_SEND_USER is on (the learner
id is data leaving the machine). Streaming asks for `stream_options.include_usage`
and does not break on the final usage chunk."""

import asyncio
import json

import httpx
import pytest

from backend import config
from backend.services import llm

_RealAsyncClient = httpx.AsyncClient

_STREAM_BODY = (
    'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
    # Final usage chunk: empty choices. It must not end the stream early or crash.
    'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":3}}\n\n'
    "data: [DONE]\n\n"
)


@pytest.fixture
def captured(monkeypatch):
    """Point the chat client at a MockTransport and capture the request bodies."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("stream"):
            return httpx.Response(
                200, text=_STREAM_BODY, headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    monkeypatch.setattr(config, "AI_BASE_URL", "http://ai.test/v1")
    monkeypatch.setattr(config, "AI_MODEL", "test-model")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )
    return bodies


def test_chat_sends_user_when_enabled(captured, monkeypatch):
    monkeypatch.setattr(config, "AI_SEND_USER", True)
    out = asyncio.run(llm.chat([{"role": "user", "content": "hi"}], user="alex"))
    assert out == "hello"
    assert captured[0]["user"] == "alex"
    assert captured[0]["model"] == "test-model"


def test_chat_does_not_send_user_when_disabled(captured, monkeypatch):
    monkeypatch.setattr(config, "AI_SEND_USER", False)
    asyncio.run(llm.chat([{"role": "user", "content": "hi"}], user="alex"))
    assert "user" not in captured[0]


def test_chat_without_user_omits_the_field(captured, monkeypatch):
    monkeypatch.setattr(config, "AI_SEND_USER", True)
    asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert "user" not in captured[0]


def _collect_stream(**kwargs) -> list[str]:
    async def _run():
        return [d async for d in llm.chat_stream([{"role": "user", "content": "hi"}], **kwargs)]

    return asyncio.run(_run())


def test_chat_stream_sends_user_and_include_usage_and_survives_usage_chunk(captured, monkeypatch):
    monkeypatch.setattr(config, "AI_SEND_USER", True)
    deltas = _collect_stream(user="alex")
    assert deltas == ["Hel", "lo"]  # the usage chunk does not break the iteration
    assert captured[0]["user"] == "alex"
    assert captured[0]["stream_options"] == {"include_usage": True}


def test_chat_stream_does_not_send_user_when_disabled(captured, monkeypatch):
    monkeypatch.setattr(config, "AI_SEND_USER", False)
    assert _collect_stream(user="alex") == ["Hel", "lo"]
    assert "user" not in captured[0]
