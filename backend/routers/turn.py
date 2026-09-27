"""Turns: /turn (blocking), /turn/stream (SSE), /read/score (modes 4 and 8) and
/pairs/score (minimal pairs).

Audio turns need speech-to-text; its AIServiceError (not configured, or no word
timestamps for pronunciation) propagates and the app maps it to 503/501. Text
turns work without it."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import memory, minimal_pairs, pronunciation
from ..schemas import ReadScoreResult, TurnResult
from ..services import stt
from ..sessions import SESSIONS
from ..teacher import (
    KICKOFF_EXPRESSIONS,
    KICKOFF_INSTRUCTION,
    synth_chunk,
    teacher_turn,
    teacher_turn_stream,
    writing_turn,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _apply_speech_rate(session: dict, speech_rate: float | None) -> None:
    """Speaking rate can change mid-session: the slow/normal/fast toggle travels
    with every turn and sticks for the next ones."""
    if speech_rate is not None:
        session["speech_rate"] = None if speech_rate == 1.0 else max(0.7, min(1.6, speech_rate))


# ---------------------------------------------------------------------------
# /turn
# ---------------------------------------------------------------------------
@router.post("/turn", response_model=TurnResult)
async def turn(
    session_id: str = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = None,
    action: str = Form("talk"),  # mode 5: "feedback" | "send"
    speech_rate: float | None = Form(None),
):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "unknown or closed session_id")
    session["last_activity"] = time.monotonic()
    _apply_speech_rate(session, speech_rate)
    # Talking closes the kickoff window (same as /turn/stream).
    session["opened"] = True

    user, lang, mode = session["user"], session["lang"], session["mode"]
    t_turn = time.perf_counter()

    # 1) Get the learner transcript (audio -> STT, or direct text).
    if audio is not None:
        raw = await audio.read()
        stt_prompt = memory.build_stt_prompt(user, lang)
        transcript = await stt.transcribe(
            raw,
            lang,
            filename=audio.filename or "turn.wav",
            content_type=audio.content_type,
            prompt=stt_prompt or None,
        )
    elif text and text.strip():
        transcript = text.strip()
    else:
        raise HTTPException(400, "the turn needs 'text' or 'audio'")

    if not transcript:
        raise HTTPException(422, "speech-to-text returned no text (empty or unintelligible audio)")

    # 2) Turn by mode: writing has two actions, the rest converse.
    if mode == 5:
        if action not in ("talk", "feedback", "send"):
            raise HTTPException(400, f"invalid action: {action!r}")
        payload = await writing_turn(
            session_id, session, transcript, "send" if action == "send" else "feedback"
        )
    else:
        payload = await teacher_turn(session_id, session, transcript)

    total_ms = (time.perf_counter() - t_turn) * 1000
    logger.info(
        "[turn] user=%s lang=%s mode=%d action=%s turn=%d total=%dms",
        user,
        lang,
        mode,
        action,
        payload["turn"],
        int(total_ms),
    )
    return payload


# ---------------------------------------------------------------------------
# /turn/stream  (SSE: streamed chat reply + per-sentence TTS)
# ---------------------------------------------------------------------------
@router.post("/turn/stream")
async def turn_stream(
    session_id: str = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = None,
    kickoff: bool = Form(False),
    speech_rate: float | None = Form(None),
) -> StreamingResponse:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "unknown or closed session_id")
    session["last_activity"] = time.monotonic()
    _apply_speech_rate(session, speech_rate)
    if session["mode"] not in (1, 2, 3, 6, 7, 8, 9):
        raise HTTPException(400, "streaming is only for conversational modes (1, 2, 3, 6, 7, 8, 9)")

    user, lang, mode = session["user"], session["lang"], session["mode"]
    on_complete = None

    if kickoff:
        # Deferred opening (defer_opening in /session/start): the teacher opens
        # streamed, without input from the learner.
        # Mode 8 gets here with turns > 0 (reading aloud scores turns): what makes
        # the kickoff unique is that the session has not OPENED a conversation
        # yet, not that there are no turns.
        if session.get("opened"):
            raise HTTPException(400, "kickoff is only allowed before the conversation opens")
        session["opened"] = True
        user_content = KICKOFF_EXPRESSIONS if mode == 7 else KICKOFF_INSTRUCTION
        if mode == 8 and session.get("read_note"):
            # The read-aloud result as context for the opening.
            user_content = f"{KICKOFF_INSTRUCTION}\n\n{session['read_note']}"
        transcript = ""
        if mode == 6 and session.get("sub_mode") == "weekly_review":
            # Same as the non-deferred path: the weekly review is persisted when
            # the opening completes successfully.
            def on_complete(parsed: dict) -> None:
                memory.write_weekly_review(user, lang, parsed["reply"])
    else:
        # Normal turn: the conversation is marked as opened (no kickoff after
        # talking).
        session["opened"] = True
        if audio is not None:
            raw = await audio.read()
            stt_prompt = memory.build_stt_prompt(user, lang)
            transcript = await stt.transcribe(
                raw,
                lang,
                filename=audio.filename or "turn.wav",
                content_type=audio.content_type,
                prompt=stt_prompt or None,
            )
        elif text and text.strip():
            transcript = text.strip()
        else:
            raise HTTPException(400, "the turn needs 'text' or 'audio'")

        if not transcript:
            raise HTTPException(
                422, "speech-to-text returned no text (empty or unintelligible audio)"
            )
        user_content = transcript

    generator = teacher_turn_stream(
        session_id, session, user_content, transcript, on_complete=on_complete
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# /read/score  (modes 4 and 8: score a read-aloud against the reference text)
# ---------------------------------------------------------------------------
@router.post("/read/score", response_model=ReadScoreResult)
async def read_score(
    session_id: str = Form(...),
    audio: UploadFile | None = None,
):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "unknown or closed session_id")
    session["last_activity"] = time.monotonic()
    if session["mode"] not in (4, 8):
        raise HTTPException(400, "/read/score is only for modes 4 and 8")
    reference = session.get("reference_text")
    if not reference:
        raise HTTPException(400, "the session has no reference text")
    if audio is None:
        raise HTTPException(400, "missing 'audio' (the read-aloud recording)")

    user, lang = session["user"], session["lang"]
    t0 = time.perf_counter()
    raw = await audio.read()
    heard_text, words = await stt.transcribe_words(
        raw,
        lang,
        filename=audio.filename or "read.wav",
        content_type=audio.content_type,
    )
    if not words and not heard_text:
        raise HTTPException(422, "no speech detected (empty or unintelligible audio)")

    result = pronunciation.score_reading(reference, words)

    # Reference audio of each weak word, for the "listen" button (None without TTS).
    session["turns"] += 1
    turn_idx = session["turns"]
    flagged: list[dict] = []
    for i, word in enumerate(result["flagged"][:20], start=1):
        # The learner's voice but at NORMAL speed: it is the pronunciation
        # reference, it must not inherit the slow/fast setting.
        url, _ = await synth_chunk(session_id, turn_idx, i, word, lang, voice=session.get("voice"))
        flagged.append({"word": word, "audio_url": url})

    s = result["summary"]
    if session["mode"] == 8:
        # The comprehension opening (kickoff) uses this to react to the reading.
        # Only the last reading counts: a retry overwrites it.
        weak = ", ".join(result["flagged"][:8])
        session["read_note"] = (
            f"(Context: the learner has just read the page aloud. Result: "
            f"{s['accuracy']}% clear ({s['ok']}/{s['total']})."
            + (f" Words that were hard: {weak}.)" if weak else ")")
        )
    # Mode 4 already has "read aloud" in its label; mode 8 does not, and the
    # closing analyst pass tells these turns apart by that label.
    label = session.get("label")
    if session["mode"] == 8:
        label = f"{label} · read aloud"
    memory.append_turn(
        user,
        lang,
        session["mode"],
        {
            "transcript": heard_text,
            "reply": (
                f"Reading: {s['accuracy']}% clear ({s['ok']}/{s['total']}). "
                f"Weak/missed: {s['weak'] + s['miss']}."
            ),
            "corrections": [],
            "new_vocab": [],
            "suggested_followup": "",
        },
        label=label,
        session_id=session_id,
    )

    logger.info(
        "[read] user=%s lang=%s acc=%d%% ok=%d weak=%d miss=%d total=%dms",
        user,
        lang,
        s["accuracy"],
        s["ok"],
        s["weak"],
        s["miss"],
        int((time.perf_counter() - t0) * 1000),
    )
    return {
        "session_id": session_id,
        "heard_text": heard_text,
        "words": result["words"],
        "summary": s,
        "flagged": flagged,
    }


# ---------------------------------------------------------------------------
# /pairs/score  (minimal pairs: the learner reads the pair, verdict without the chat model)
# ---------------------------------------------------------------------------
@router.post("/pairs/score")
async def pairs_score(
    session_id: str = Form(...),
    pair_index: int = Form(...),
    audio: UploadFile = File(...),
):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "unknown or closed session_id")
    session["last_activity"] = time.monotonic()
    pairs = session.get("pairs")
    if not pairs:
        raise HTTPException(400, "/pairs/score is only for minimal pairs sessions")
    if not (0 <= pair_index < len(pairs)):
        raise HTTPException(400, f"pair_index out of range: {pair_index}")

    user, lang = session["user"], session["lang"]
    pair = pairs[pair_index]
    raw = await audio.read()
    # NO prompt: we want what was said, not what the recognizer would expect.
    heard_text, words = await stt.transcribe_words(
        raw, lang, filename=audio.filename or "pair.wav", content_type=audio.content_type
    )
    v = minimal_pairs.verdict(pair["words"], [w.get("word", "") for w in words])

    pair_label = "-".join(pair["words"])
    if v["status"] in ("ok", "same"):
        minimal_pairs.record_attempt(user, lang, pair["contrast"], pair_label, v["status"] == "ok")
        session.setdefault("pair_results", []).append({"pair": pair_label, "status": v["status"]})
    session["turns"] += 1
    memory.append_turn(
        user,
        lang,
        session["mode"],
        {
            "transcript": heard_text,
            "reply": f"Pair {pair_label} ({pair['contrast']}): "
            + {
                "ok": "distinguished",
                "same": f"not distinguished (sounded like '{v['heard_as']}' twice)",
                "unclear": "not recognized",
            }[v["status"]],
            "corrections": [],
            "new_vocab": [],
            "suggested_followup": "",
        },
        label=session.get("label"),
        session_id=session_id,
    )
    return {"session_id": session_id, "pair_index": pair_index, **v}
