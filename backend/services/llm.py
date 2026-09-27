"""Chat client for any OpenAI-compatible /chat/completions endpoint."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Literal

import httpx

from .. import config
from ..grammar import TEACHER_GBNF
from . import AIServiceError, auth_headers, wrap_http_error

logger = logging.getLogger(__name__)

# text: free prose. json: one JSON object. teacher: the teacher reply contract
# (a JSON object too, but gbnf mode can enforce its exact shape).
Output = Literal["text", "json", "teacher"]

# Set to False the first time the server rejects response_format in auto mode,
# so the app keeps working on servers that do not support it.
_json_mode_supported = True


def configured() -> bool:
    return bool(config.AI_BASE_URL and config.AI_MODEL)


def _require_configured() -> None:
    if not configured():
        raise AIServiceError(
            "chat",
            "not_configured",
            "No chat model configured. Set AI_BASE_URL and AI_MODEL (see README).",
        )


def _structured_fields(output: Output) -> dict:
    """Extra request fields that ask the server for JSON, according to AI_JSON_MODE."""
    if output == "text" or config.AI_JSON_MODE == "off":
        return {}
    if config.AI_JSON_MODE == "gbnf":
        if output == "teacher":
            return {"grammar": TEACHER_GBNF}
        return {"response_format": {"type": "json_object"}}
    if config.AI_JSON_MODE == "json_object" or _json_mode_supported:
        return {"response_format": {"type": "json_object"}}
    return {}


def _is_format_rejection(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code not in (400, 422):
        return False
    text = exc.response.text.lower()
    return "response_format" in text or "json_object" in text or "json_schema" in text


def _body(
    messages: list[dict],
    *,
    temperature: float | None,
    max_tokens: int | None,
    model: str | None,
    user: str | None,
    output: Output,
    stream: bool,
) -> dict:
    body: dict = {
        "model": model or config.AI_MODEL,
        "messages": messages,
        "temperature": config.AI_TEMPERATURE if temperature is None else temperature,
        "max_tokens": config.AI_MAX_TOKENS if max_tokens is None else max_tokens,
    }
    if stream:
        body["stream"] = True
        # Asks the server for a final chunk with token usage.
        body["stream_options"] = {"include_usage": True}
    if user and config.AI_SEND_USER:
        body["user"] = user
    body.update(_structured_fields(output))
    return body


def _disable_json_mode() -> None:
    global _json_mode_supported
    if _json_mode_supported:
        logger.warning(
            "[llm] the chat server rejected response_format; continuing without it "
            "(set AI_JSON_MODE=off to skip this probe)"
        )
    _json_mode_supported = False


def _can_retry_without_format(exc: httpx.HTTPStatusError, output: Output) -> bool:
    return (
        output != "text"
        and config.AI_JSON_MODE == "auto"
        and _json_mode_supported
        and _is_format_rejection(exc)
    )


async def chat(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    *,
    output: Output = "text",
    model: str | None = None,
    user: str | None = None,
) -> str:
    """One chat completion. Returns the assistant content as raw text."""
    _require_configured()
    url = f"{config.AI_BASE_URL}/chat/completions"
    headers = {**auth_headers(config.AI_API_KEY), "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT) as client:
            body = _body(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                user=user,
                output=output,
                stream=False,
            )
            resp = await client.post(url, headers=headers, json=body)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if not _can_retry_without_format(exc, output):
                    raise
                _disable_json_mode()
                body.pop("response_format", None)
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        raise wrap_http_error("chat", exc, config.AI_BASE_URL) from exc
    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AIServiceError(
            "chat", "bad_response", "The chat server returned no choices."
        ) from exc
    usage = payload.get("usage") or {}
    logger.info(
        "[llm] total=%dms prompt_tok=%s completion_tok=%s",
        int((time.perf_counter() - t0) * 1000),
        usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"),
    )
    return content


async def chat_stream(
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    *,
    output: Output = "text",
    model: str | None = None,
    user: str | None = None,
) -> AsyncIterator[str]:
    """Streamed chat completion. Yields the assistant text deltas.

    Parses the OpenAI server-sent events (`data: {...}` lines and `[DONE]`).
    """
    _require_configured()
    url = f"{config.AI_BASE_URL}/chat/completions"
    headers = {**auth_headers(config.AI_API_KEY), "Content-Type": "application/json"}
    body = _body(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        user=user,
        output=output,
        stream=True,
    )
    t0 = time.perf_counter()
    t_first: float | None = None
    n_deltas = 0
    usage: dict | None = None
    try:
        async with httpx.AsyncClient(timeout=config.AI_TIMEOUT) as client:
            for attempt in (1, 2):
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            if attempt == 1 and _can_retry_without_format(exc, output):
                                _disable_json_mode()
                                body.pop("response_format", None)
                                continue
                            raise
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        # The usage chunk arrives with empty choices.
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0].get("delta") or {}).get("content")
                        if not delta:
                            continue
                        if t_first is None:
                            t_first = time.perf_counter()
                        n_deltas += 1
                        yield delta
                break
    except AIServiceError:
        raise
    except Exception as exc:
        raise wrap_http_error("chat", exc, config.AI_BASE_URL) from exc
    logger.info(
        "[llm-stream] total=%dms first_token=%dms deltas=%d prompt_tok=%s completion_tok=%s",
        int((time.perf_counter() - t0) * 1000),
        int((t_first - t0) * 1000) if t_first is not None else -1,
        n_deltas,
        (usage or {}).get("prompt_tokens", "?"),
        (usage or {}).get("completion_tokens", "?"),
    )


async def warmup(system_prompt: str | None = None, user: str | None = None) -> None:
    """Warm the model up so the first real turn is fast.

    With a system prompt, servers with prompt caching (llama.cpp, Ollama) keep
    that prefix and skip most of the prefill on the first turn. Fire-and-forget:
    errors are ignored, the first real completion will simply be slower.
    """
    if not configured():
        return
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [
        {"role": "user", "content": "."}
    ]
    try:
        await chat(messages, temperature=0.0, max_tokens=1, user=user)
    except Exception:
        logger.debug("[llm] warmup failed", exc_info=True)
