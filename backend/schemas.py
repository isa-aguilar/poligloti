"""Pydantic response models of the main endpoints.

They mirror the keys and types of the JSON the backend returns (the frontend
contract); their purpose is that GET /openapi.json exposes real response schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Correction(BaseModel):
    original: str = ""
    corrected: str = ""
    note: str = ""


class VocabItem(BaseModel):
    term: str
    translation: str = ""
    example: str = ""


class TurnResult(BaseModel):
    session_id: str
    turn: int
    transcript: str
    reply: str
    corrections: list[Correction]
    new_vocab: list[VocabItem]
    suggested_followup: str
    revised: str = ""
    audio_url: str | None = None


class SessionStartResult(BaseModel):
    session_id: str
    user: str
    target_language: str
    mode: int
    # No system_prompt: it carries the learner's whole memory and the client
    # does not need it. It stays in the server-side session state.
    scenario_info: dict | None = None
    opening: TurnResult | None = None
    reference_text: str | None = None
    weekly_review: bool = False
    # defer_opening=true in modes with an opening (2, 3, 6, 7, 9): the opening
    # arrives later via /turn/stream with kickoff=1.
    opening_pending: bool = False
    # Mode 4 with pair_mode: the session's minimal pairs, with pre-synthesized
    # audio when TTS is configured (audio urls may be None otherwise).
    pairs: list | None = None


class SessionEndResult(BaseModel):
    # The close adds fields depending on the mode (progress_updated, vocab_added,
    # assessment, levelup...): extra="allow" lets them through without fixing them here.
    model_config = ConfigDict(extra="allow")

    closed: str
    turns: int


class ReadScoreResult(BaseModel):
    session_id: str
    heard_text: str
    words: list[dict]
    summary: dict
    flagged: list[dict]


class ProgressDim(BaseModel):
    key: str
    label: str
    score: int | None = None


class WeeklyReview(BaseModel):
    week: str
    text: str


class ProgressHistoryPoint(BaseModel):
    """One point of the progress curve: date + the 8 scores + the note."""

    date: str
    scores: dict[str, int]
    note: str = ""


class ProgressData(BaseModel):
    user: str
    lang: str
    has_data: bool
    has_assessment: bool = False
    cefr: str
    next_cefr: str | None = None
    target_cefr: str | None = None
    avg_score: int
    levelup_eligible: bool
    dims: list[ProgressDim]
    active_errors: list[str]
    resolved_errors: list[str]
    focus: str
    milestones: list[str]
    weekly_reviews: list[WeeklyReview]
    expressions_count: int
    history: list[ProgressHistoryPoint] = []
    updated: str | None = None


class ServiceStatus(BaseModel):
    configured: bool
    # Only present once a probe has run (or with ?deep=1).
    reachable: bool | None = None
    # Why the service is missing or failing, when it is.
    detail: str | None = None


class ChatStatus(ServiceStatus):
    vision: bool | None = None


class SpeechStatus(ServiceStatus):
    # None until the server has been seen returning (or not) word timestamps.
    word_timestamps: bool | None = None


class VoiceStatus(ServiceStatus):
    languages: list[str] | None = None


class HealthServices(BaseModel):
    chat: ChatStatus
    stt: SpeechStatus
    tts: VoiceStatus


class HealthResult(BaseModel):
    # ok | degraded | setup_required
    status: str
    version: str
    services: HealthServices
    active_sessions: int
