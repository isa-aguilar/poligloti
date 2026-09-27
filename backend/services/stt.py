"""Speech-to-text client for any OpenAI-compatible /audio/transcriptions endpoint.

Browsers record WebM/Opus (Chrome, Firefox) or MP4/AAC (Safari). Some servers
(whisper.cpp in particular) only decode WAV, so when ffmpeg is available any
non-WAV upload is transcoded to 16 kHz mono WAV first. Without ffmpeg the audio
is sent as recorded, which is fine for OpenAI, Groq and speaches.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time

import httpx

from .. import config
from . import AIServiceError, auth_headers, wrap_http_error

logger = logging.getLogger(__name__)

_FFMPEG = shutil.which("ffmpeg")

# None = not known yet (auto mode), True/False once observed or configured.
_word_timestamps: bool | None = {"true": True, "false": False}.get(config.STT_WORD_TIMESTAMPS)


def configured() -> bool:
    return bool(config.STT_BASE_URL and config.STT_MODEL)


def word_timestamps_supported() -> bool | None:
    """Whether the server returns per-word timings. None until the first try."""
    if not configured():
        return False
    return _word_timestamps


def _require_configured() -> None:
    if not configured():
        raise AIServiceError(
            "speech-to-text",
            "not_configured",
            "No speech-to-text model configured. Set STT_MODEL (see README).",
        )


def _looks_like_wav(audio: bytes) -> bool:
    return len(audio) >= 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"


async def _to_wav16k_mono(audio: bytes) -> bytes:
    """Transcode any browser format (webm/opus, mp4/aac, ogg) to 16 kHz mono WAV."""
    assert _FFMPEG
    proc = await asyncio.create_subprocess_exec(
        _FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(audio)
    if proc.returncode != 0:
        # Usually an empty or cut-off recording (a very short tap). The ffmpeg
        # details help debugging but mean nothing to the learner.
        logger.warning(
            "[stt] ffmpeg could not decode the recording: %s", err.decode(errors="replace")[:300]
        )
        raise _unreadable_recording()
    return out


def _unreadable_recording() -> AIServiceError:
    return AIServiceError(
        "speech-to-text",
        "bad_audio",
        "The recording could not be read: it may be empty or cut off. "
        "Try again and speak for a little longer.",
    )


# Below this size a browser recording holds no usable speech (headers only).
_MIN_RECORDING_BYTES = 1000


async def _prepare(audio: bytes, filename: str, content_type: str | None) -> tuple[bytes, str, str]:
    if len(audio) < _MIN_RECORDING_BYTES:
        raise _unreadable_recording()
    if _looks_like_wav(audio) or not _FFMPEG:
        return audio, filename, content_type or "application/octet-stream"
    wav = await _to_wav16k_mono(audio)
    return wav, filename.rsplit(".", 1)[0] + ".wav", "audio/wav"


async def _post(files: dict, data: dict) -> dict:
    url = f"{config.STT_BASE_URL}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=config.STT_TIMEOUT) as client:
            resp = await client.post(
                url, headers=auth_headers(config.STT_API_KEY), files=files, data=data
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        raise wrap_http_error("speech-to-text", exc, config.STT_BASE_URL) from exc


async def transcribe(
    audio: bytes,
    language: str,
    filename: str = "turn.webm",
    content_type: str | None = None,
    prompt: str | None = None,
) -> str:
    """Transcribe one recording in `language`.

    `prompt` is context text in the same language (proper names, recent
    vocabulary) that biases recognition towards words the learner uses.
    """
    _require_configured()
    t0 = time.perf_counter()
    audio, filename, content_type = await _prepare(audio, filename, content_type)
    data = {"model": config.STT_MODEL, "language": language}
    if prompt:
        data["prompt"] = prompt
    payload = await _post({"file": (filename, audio, content_type)}, data)
    logger.info(
        "[stt] total=%dms prompt_len=%d",
        int((time.perf_counter() - t0) * 1000),
        len(prompt or ""),
    )
    return (payload.get("text") or "").strip()


def _words_from_payload(payload: dict) -> list[dict]:
    """Normalize the two word-timestamp shapes servers return.

    OpenAI and speaches put whole words in a top-level `words` list. whisper.cpp
    nests them under `segments[].words` and splits long words into sub-tokens:
    a leading space starts a new word, a piece without one continues the
    previous word. Merged words take the lowest probability of their pieces,
    since the least certain syllable is the one worth flagging.
    """
    top = payload.get("words")
    if isinstance(top, list) and top:
        return [
            {
                "word": (w.get("word") or "").strip(),
                "start": w.get("start"),
                "end": w.get("end"),
                "probability": w.get("probability"),
            }
            for w in top
            if (w.get("word") or "").strip()
        ]

    words: list[dict] = []
    pending: list[float] = []
    for seg in payload.get("segments") or []:
        for w in seg.get("words") or []:
            surface = w.get("word") or ""
            token = surface.strip()
            if not token:
                continue
            prob = w.get("probability")
            if surface[:1].isspace() or not words:
                if words:
                    words[-1]["probability"] = min(pending) if pending else None
                pending = [] if prob is None else [prob]
                words.append(
                    {
                        "word": token,
                        "start": w.get("start"),
                        "end": w.get("end"),
                        "probability": prob,
                    }
                )
            else:
                words[-1]["word"] += token
                words[-1]["end"] = w.get("end")
                if prob is not None:
                    pending.append(prob)
    if words:
        words[-1]["probability"] = min(pending) if pending else words[-1]["probability"]
    return words


async def transcribe_words(
    audio: bytes,
    language: str,
    filename: str = "read.webm",
    content_type: str | None = None,
    prompt: str | None = None,
) -> tuple[str, list[dict]]:
    """Transcribe and return (text, words) with per-word timings.

    Each word is {word, start, end, probability}. The probability is the
    recognizer's confidence, a proxy for how clearly the word was said (not a
    phonetic score); it is None on servers that do not report it.
    """
    global _word_timestamps
    _require_configured()
    if _word_timestamps is False:
        raise AIServiceError(
            "speech-to-text",
            "unsupported",
            "This speech-to-text server does not return word timestamps, "
            "so pronunciation practice is not available.",
        )
    t0 = time.perf_counter()
    audio, filename, content_type = await _prepare(audio, filename, content_type)
    data = {
        "model": config.STT_MODEL,
        "language": language,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    if prompt:
        data["prompt"] = prompt
    payload = await _post({"file": (filename, audio, content_type)}, data)
    text = (payload.get("text") or "").strip()
    words = _words_from_payload(payload)
    if text and not words and _word_timestamps is None:
        _word_timestamps = False
        logger.warning("[stt] the server returned text without word timestamps; disabling")
        raise AIServiceError(
            "speech-to-text",
            "unsupported",
            "This speech-to-text server does not return word timestamps, "
            "so pronunciation practice is not available.",
        )
    if words:
        _word_timestamps = True
    logger.info(
        "[stt-words] total=%dms words=%d", int((time.perf_counter() - t0) * 1000), len(words)
    )
    return text, words
