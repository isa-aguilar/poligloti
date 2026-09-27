"""What each AI service can do right now: configured, reachable, capabilities.

The frontend adapts to this: no chat means a setup screen, no speech-to-text
means typing instead of talking, no text-to-speech means an on-device browser
voice, no vision model hides the page photo, no word timestamps hides
pronunciation practice.
"""

from __future__ import annotations

import logging

import httpx

from .. import config
from . import auth_headers, llm, stt, tts

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 12.0

# Result of the last probe, per service: (reachable, detail). Empty until the
# first probe runs, which happens in the background at startup.
_last_probe: dict[str, tuple[bool, str | None]] = {}


async def _probe_chat(client: httpx.AsyncClient) -> tuple[bool, str | None]:
    """A one-token completion. Listing models proves nothing: a server can list
    a model that fails to load. The only proof that it answers is an answer."""
    body = {
        "model": config.AI_MODEL,
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    headers = {**auth_headers(config.AI_API_KEY), "Content-Type": "application/json"}
    try:
        r = await client.post(f"{config.AI_BASE_URL}/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException:
        return False, f"The model {config.AI_MODEL} is slow to answer; it may still be loading."
    except httpx.HTTPError:
        return False, f"Cannot reach the chat server at {config.AI_BASE_URL}."
    if r.status_code in (401, 403):
        return False, "The chat server rejected the API key."
    if r.status_code != 200:
        return False, f"The chat server answered HTTP {r.status_code} for model {config.AI_MODEL}."
    try:
        if r.json()["choices"]:
            return True, None
    except (ValueError, KeyError, TypeError):
        pass
    return False, f"The model {config.AI_MODEL} returned an empty answer."


async def _probe_server(
    client: httpx.AsyncClient, base_url: str, api_key: str, service: str
) -> tuple[bool, str | None]:
    """Cheap reachability check. Any HTTP answer below 500 means a server is there;
    a real transcription or synthesis on every app start would cost more than it tells."""
    try:
        r = await client.get(f"{base_url}/models", headers=auth_headers(api_key))
    except httpx.HTTPError:
        return False, f"Cannot reach the {service} server at {base_url}."
    if r.status_code in (401, 403):
        return False, f"The {service} server rejected the API key."
    if r.status_code >= 500:
        return False, f"The {service} server answered HTTP {r.status_code}."
    return True, None


async def probe() -> None:
    """Probe every configured service and remember the result."""
    results: dict[str, tuple[bool, str | None]] = {}
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
        if llm.configured():
            results["chat"] = await _probe_chat(client)
        if stt.configured():
            results["stt"] = await _probe_server(
                client, config.STT_BASE_URL, config.STT_API_KEY, "speech-to-text"
            )
        if tts.configured():
            results["tts"] = await _probe_server(
                client, config.TTS_BASE_URL, config.TTS_API_KEY, "text-to-speech"
            )
    _last_probe.clear()
    _last_probe.update(results)
    for name, (ok, detail) in results.items():
        if not ok:
            logger.warning("[status] %s: %s", name, detail)


async def safe_probe() -> None:
    try:
        await probe()
    except Exception:
        logger.exception("[status] probe failed")


def _entry(name: str, is_configured: bool, missing: str) -> dict:
    entry: dict = {"configured": is_configured}
    if not is_configured:
        entry["detail"] = missing
        return entry
    if name in _last_probe:
        ok, detail = _last_probe[name]
        entry["reachable"] = ok
        if detail:
            entry["detail"] = detail
    return entry


def snapshot() -> dict:
    """Service status for /health and the frontend."""
    chat = _entry("chat", llm.configured(), "Set AI_BASE_URL and AI_MODEL.")
    chat["vision"] = bool(config.AI_VISION_MODEL) and llm.configured()
    speech = _entry("stt", stt.configured(), "Set STT_MODEL to talk instead of typing.")
    speech["word_timestamps"] = stt.word_timestamps_supported()
    voice = _entry(
        "tts",
        tts.configured(),
        "Set TTS_MODEL and TTS_VOICE_<LANG> for server voices; the browser voice is used meanwhile.",
    )
    voice["languages"] = [code for code in config.SUPPORTED_LANGS if tts.configured(code)]
    return {"chat": chat, "stt": speech, "tts": voice}


def overall(services: dict) -> str:
    """setup_required: no chat model. degraded: a configured service does not answer.
    Leaving speech-to-text or text-to-speech unset is a valid choice, not a fault."""
    if not services["chat"]["configured"]:
        return "setup_required"
    if any(s["configured"] and s.get("reachable") is False for s in services.values()):
        return "degraded"
    return "ok"
