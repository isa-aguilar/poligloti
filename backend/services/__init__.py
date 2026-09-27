"""Clients for the three AI services (chat, speech-to-text, text-to-speech).

All of them speak the OpenAI HTTP protocol, so any compatible server works:
Ollama, LM Studio, llama.cpp, speaches, OpenAI, Groq and others.
"""

from __future__ import annotations

import httpx


class AIServiceError(Exception):
    """An AI service could not do its job. Carries a stable code for the API.

    Codes: not_configured, unreachable, timeout, unauthorized, bad_response,
    unsupported, bad_audio (the recording itself could not be read).
    """

    def __init__(self, service: str, code: str, message: str) -> None:
        super().__init__(message)
        self.service = service
        self.code = code
        self.message = message


def auth_headers(api_key: str) -> dict[str, str]:
    # identity: some local servers send gzip that breaks streaming clients.
    headers = {"Accept-Encoding": "identity"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def wrap_http_error(service: str, exc: Exception, base_url: str) -> AIServiceError:
    """Translate an httpx failure into an error the learner can act on."""
    if isinstance(exc, AIServiceError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return AIServiceError(
            service, "timeout", f"The {service} server at {base_url} took too long to answer."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return AIServiceError(
                service,
                "unauthorized",
                f"The {service} server rejected the API key (HTTP {status}).",
            )
        body = exc.response.text[:200].strip()
        return AIServiceError(
            service,
            "bad_response",
            f"The {service} server answered HTTP {status}" + (f": {body}" if body else "."),
        )
    if isinstance(exc, httpx.HTTPError):
        return AIServiceError(
            service, "unreachable", f"Cannot reach the {service} server at {base_url}."
        )
    return AIServiceError(service, "bad_response", f"Unexpected {service} error: {exc}")
