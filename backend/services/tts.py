"""Text-to-speech client for any OpenAI-compatible /audio/speech endpoint.

Returns WAV bytes. Without a TTS server configured the app still works: the
browser reads the replies aloud with an on-device voice, or shows text only.
"""

from __future__ import annotations

import logging
import time

import httpx

from .. import config
from . import AIServiceError, auth_headers, wrap_http_error

logger = logging.getLogger(__name__)


def model_for(language: str) -> str:
    return config.LANGUAGES.get(language, {}).get("tts_model") or config.TTS_MODEL


def configured(language: str | None = None) -> bool:
    """TTS needs a server, and for a language also a model and a voice.
    Without a language: whether at least one language has a voice."""
    if not config.TTS_BASE_URL:
        return False
    if language is None:
        return any(configured(code) for code in config.SUPPORTED_LANGS)
    return bool(model_for(language) and allowed_voices(language))


def voice_for(language: str) -> str | None:
    voices = config.LANGUAGES.get(language, {}).get("voices") or []
    return voices[0] if voices else None


def allowed_voices(language: str) -> list[str]:
    return list(config.LANGUAGES.get(language, {}).get("voices") or [])


async def synthesize(
    text: str,
    language: str,
    voice: str | None = None,
    length_scale: float | None = None,
) -> bytes:
    """Synthesize `text` in `language`.

    `voice` overrides the language default and must be one of its configured
    voices. `length_scale` controls the pace (>1 slower); it is sent as the
    OpenAI `speed` field, which is its inverse.
    """
    if not configured(language):
        raise AIServiceError(
            "text-to-speech",
            "not_configured",
            f"No text-to-speech voice configured for {config.LANG_NAMES.get(language, language)}.",
        )
    chosen = voice if voice in allowed_voices(language) else voice_for(language)
    body: dict = {
        "model": model_for(language),
        "input": text,
        "voice": chosen,
        "response_format": "wav",
    }
    if length_scale and length_scale != 1.0:
        body["speed"] = round(1.0 / length_scale, 3)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.TTS_TIMEOUT) as client:
            resp = await client.post(
                f"{config.TTS_BASE_URL}/audio/speech",
                json=body,
                headers=auth_headers(config.TTS_API_KEY),
            )
            resp.raise_for_status()
            content = resp.content
    except Exception as exc:
        raise wrap_http_error("text-to-speech", exc, config.TTS_BASE_URL) from exc
    logger.info(
        "[tts] total=%dms chars=%d bytes=%d voice=%s",
        int((time.perf_counter() - t0) * 1000),
        len(text),
        len(content),
        chosen,
    )
    return content
