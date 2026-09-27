"""Configuration from environment variables.

Every setting has a safe default except the AI endpoints, which have none on
purpose: the app never guesses which model server you run. See `.env.example`
for a commented template. A `.env` file in the repository root or in
`backend/` is loaded if present; real environment variables win over it.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


def _load_dotenv() -> None:
    for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


if os.getenv("POLIGLOTI_SKIP_DOTENV") != "1":
    _load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _path(env: str, default: Path) -> Path:
    """A path setting. Relative paths are relative to the repository root."""
    raw = os.getenv(env)
    if not raw:
        return default
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else REPO_ROOT / path).resolve()


def _bool(env: str, default: bool) -> bool:
    raw = _env(env).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# AI services. Three independent OpenAI-compatible endpoints. Speech-to-text and
# text-to-speech inherit the chat base URL and key unless set on their own, so a
# single cloud key covers everything while local servers can be split up.
# ---------------------------------------------------------------------------
AI_BASE_URL = _env("AI_BASE_URL").rstrip("/")
AI_API_KEY = _env("AI_API_KEY")
AI_MODEL = _env("AI_MODEL")
AI_VISION_MODEL = _env("AI_VISION_MODEL")

STT_BASE_URL = (_env("STT_BASE_URL") or AI_BASE_URL).rstrip("/")
STT_API_KEY = _env("STT_API_KEY") or AI_API_KEY
STT_MODEL = _env("STT_MODEL")
# auto: assume the server returns word timestamps and switch the feature off the
# first time a transcription comes back without them.
STT_WORD_TIMESTAMPS = _env("STT_WORD_TIMESTAMPS", "auto").lower()

TTS_BASE_URL = (_env("TTS_BASE_URL") or AI_BASE_URL).rstrip("/")
TTS_API_KEY = _env("TTS_API_KEY") or AI_API_KEY
TTS_MODEL = _env("TTS_MODEL")

# How to ask the chat model for JSON. auto: send response_format=json_object and
# drop it for good if the server rejects it. gbnf: llama.cpp grammar (strictest,
# llama.cpp-based servers only). off: plain text, rely on the tolerant parser.
AI_JSON_MODE = _env("AI_JSON_MODE", "auto").lower()
# Send the learner id as the OpenAI `user` field (useful behind a gateway that
# attributes usage per user). Off by default: it is data leaving the machine.
AI_SEND_USER = _bool("AI_SEND_USER", False)

# ---------------------------------------------------------------------------
# Languages. Single source of truth: adding a language means an entry here plus
# backend/prompts/<lang>/ and its seed files. Everything else derives from this.
# ---------------------------------------------------------------------------
_LANGUAGE_NAMES = {"de": "German", "en": "English", "fr": "French"}


def _voices(lang: str) -> list[str]:
    """TTS voices for a language: TTS_VOICE_<LANG>, comma separated, first = default."""
    raw = _env(f"TTS_VOICE_{lang.upper()}")
    return [v.strip() for v in raw.split(",") if v.strip()]


# Some servers need a different TTS model per language (with speaches, every
# Piper voice is its own model): TTS_MODEL_<LANG> overrides TTS_MODEL.
LANGUAGES: dict[str, dict] = {
    code: {
        "name": name,
        "voices": _voices(code),
        "tts_model": _env(f"TTS_MODEL_{code.upper()}") or TTS_MODEL,
    }
    for code, name in _LANGUAGE_NAMES.items()
}
SUPPORTED_LANGS = tuple(LANGUAGES)
LANG_NAMES = {code: spec["name"] for code, spec in LANGUAGES.items()}

# Language of explanations and corrections (the learner's own language).
UI_LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German"}
SUPPORT_LANG = _env("SUPPORT_LANG", "en")
if SUPPORT_LANG not in UI_LANG_NAMES:
    SUPPORT_LANG = "en"

# Teacher speaking rate as a length multiplier (>1 slower). Sent to the TTS
# server as the OpenAI `speed` field (its inverse).
SPEECH_RATES = {"slow": 1.3, "normal": 1.0, "fast": 0.85}

# ---------------------------------------------------------------------------
# Storage and server.
# ---------------------------------------------------------------------------
DATA_DIR = _path("DATA_DIR", REPO_ROOT / "data")
PROMPTS_ROOT = _path("PROMPTS_ROOT", BACKEND_DIR / "prompts")
AUDIO_ROOT = _path("AUDIO_ROOT", REPO_ROOT / ".runtime" / "audio")
# If the frontend has been built, FastAPI serves it at "/".
FRONTEND_DIST = _path("FRONTEND_DIST", REPO_ROOT / "frontend" / "dist")

HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8100"))
CORS_ORIGINS = [
    o.strip()
    for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# Teaching and generation limits.
# ---------------------------------------------------------------------------
MAX_CORRECTIONS = int(_env("MAX_CORRECTIONS", "3"))
AI_MAX_TOKENS = int(_env("AI_MAX_TOKENS", "320"))
AI_TEMPERATURE = float(_env("AI_TEMPERATURE", "0.4"))
# Mode 5 feedback carries the full revised draft; the colleague reply is short.
AI_MAX_TOKENS_FEEDBACK = int(_env("AI_MAX_TOKENS_FEEDBACK", "600"))
AI_MAX_TOKENS_COLLEAGUE = int(_env("AI_MAX_TOKENS_COLLEAGUE", "400"))
OCR_MAX_TOKENS = int(_env("OCR_MAX_TOKENS", "2800"))

# Mode 3 (guided reading): cap on the pasted text, which goes into the system
# prompt on every turn.
READING_MAX_CHARS = int(_env("READING_MAX_CHARS", "6000"))
# Mode 8 (book): cap on the text of one page.
BOOK_MAX_CHARS = int(_env("BOOK_MAX_CHARS", "6000"))

# How much of each memory file goes into the system prompt on every turn.
PROGRESS_TAIL_LINES = int(_env("PROGRESS_TAIL_LINES", "12"))
VOCAB_TAIL_LINES = int(_env("VOCAB_TAIL_LINES", "40"))
EXPRESSIONS_TAIL_LINES = int(_env("EXPRESSIONS_TAIL_LINES", "30"))

# Streaming: minimum sentence length (chars) before it is sent to TTS. Higher
# means fewer odd cuts at abbreviations but a longer wait for the first audio.
TTS_CHUNK_MIN_CHARS = int(_env("TTS_CHUNK_MIN_CHARS", "30"))

# Speech-to-text prompt: recent vocabulary and proper names that bias the
# transcription towards words the learner actually uses.
STT_PROMPT_VOCAB_TAIL = int(_env("STT_PROMPT_VOCAB_TAIL", "20"))
STT_PROMPT_MAX_CHARS = int(_env("STT_PROMPT_MAX_CHARS", "400"))

# HTTP timeouts in seconds. A cold local model can take a while to load.
AI_TIMEOUT = float(_env("AI_TIMEOUT", "120"))
STT_TIMEOUT = float(_env("STT_TIMEOUT", "120"))
TTS_TIMEOUT = float(_env("TTS_TIMEOUT", "120"))

# Orphan sessions (the end-of-session beacon never arrived) are finalized after
# SESSION_TTL_S without activity, checked every SESSION_SWEEP_INTERVAL_S.
SESSION_TTL_S = int(_env("SESSION_TTL_S", "7200"))
SESSION_SWEEP_INTERVAL_S = int(_env("SESSION_SWEEP_INTERVAL_S", "900"))

# ---------------------------------------------------------------------------
# Progress system. Eight skills on a CEFR spine. The key is used on disk
# (skill-tracker.md) and in the API; the label is what the learner sees.
# ---------------------------------------------------------------------------
SKILL_DIMS = [
    ("pronunciation", "Pronunciation"),
    ("grammar", "Grammar"),
    ("active_vocab", "Active vocabulary"),
    ("technical_vocab", "Work vocabulary"),
    ("listening", "Listening"),
    ("reading", "Reading"),
    ("writing", "Writing"),
    ("speaking", "Speaking fluency"),
]
SKILL_KEYS = [k for k, _ in SKILL_DIMS]

CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
# Average score that makes the app offer a level-up test.
LEVELUP_SCORE_THRESHOLD = int(_env("LEVELUP_SCORE_THRESHOLD", "70"))

# Modes: 1-5 daily practice, 6 assessment, 7 expressions, 8 book, 9 lesson.
SUPPORTED_MODES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Mode 4 (read aloud). Generated text length and token cap.
READ_GEN_WORDS = int(_env("READ_GEN_WORDS", "90"))
READ_GEN_MAX_TOKENS = int(_env("READ_GEN_MAX_TOKENS", "400"))
READ_MAX_CHARS = int(_env("READ_MAX_CHARS", "1200"))
# Per-word recognition confidence: >= OK is green, between WEAK and OK amber,
# below or mismatched red. Only used when the server reports probabilities.
READ_WORD_PROB_OK = float(_env("READ_WORD_PROB_OK", "0.7"))
READ_WORD_PROB_WEAK = float(_env("READ_WORD_PROB_WEAK", "0.45"))

# Mode 4 (minimal pairs): pairs per session.
PAIRS_PER_SESSION = int(_env("PAIRS_PER_SESSION", "8"))
