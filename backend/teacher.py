"""Teacher turns: chat model + history + TTS + persistence.

Blocking version (`teacher_turn`), SSE streaming (`teacher_turn_stream`), the
mode 5 turn (`writing_turn`) and openings (kickoff, weekly review, reading
generation). TEACHER turns ask the chat service for the teacher reply contract
(`output="teacher"`); the mode 5 colleague and reading generation have other
formats and use plain text.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime

from . import config, llm_parse, memory, prompt_builder
from .reply_stream import ReplyStreamExtractor
from .services import AIServiceError, llm, tts

logger = logging.getLogger(__name__)

KICKOFF_INSTRUCTION = (
    "(The session starts now. Open the conversation yourself following the mode "
    "instructions: greet in character and start the scene, or introduce the "
    "working text. Do not wait for input from the learner.)"
)

KICKOFF_EXPRESSIONS = (
    "(The session starts now. You open: briefly greet the learner by name and go "
    "straight to the FIRST idiomatic expression of the theme, following the mode "
    "contract: the expression inside `reply` and in `new_vocab` with its real "
    "meaning and an example. Do not wait for input from the learner; end by "
    "inviting them to use it in a sentence.)"
)


def _filter_corrections(corrections: list, said: str) -> list:
    """Corrections the learner gets to see.

    Drops corrections that quote something the learner did not say. This lives in
    code, not in the prompt, because asking the model not to do it is no
    guarantee.
    """
    return llm_parse.drop_stale_corrections(corrections, said)


async def _synthesize_turn(session_id: str, session: dict, text: str, turn_idx: int):
    """Synthesize a whole reply to disk. Returns (url, warning).

    Without TTS for the language it returns (None, None) silently: the browser
    speaks instead. A failing voice never breaks the turn.
    """
    lang = session["lang"]
    if not tts.configured(lang):
        return None, None
    try:
        wav = await tts.synthesize(text, lang, **voice_opts(session))
        out_dir = config.AUDIO_ROOT / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{turn_idx:03d}.wav").write_bytes(wav)
        return f"/audio/{session_id}/{turn_idx:03d}.wav", None
    except Exception as exc:
        return None, f"tts_failed: {exc}"


async def teacher_turn(
    session_id: str,
    session: dict,
    user_content: str,
    *,
    transcript: str | None = None,
    synthesize: bool = True,
    max_tokens: int | None = None,
    label: str | None = None,
) -> dict:
    """Chat model + history + TTS + persistence of one teacher turn.

    `user_content` is what the model sees; `transcript` is what gets persisted
    and returned as the learner's turn (they differ in the kickoff and in writing
    feedback, where the model content carries extra context).
    """
    user, lang, mode = session["user"], session["lang"], session["mode"]
    shown = user_content if transcript is None else transcript

    messages = (
        [{"role": "system", "content": session["system_prompt"]}]
        + session["history"]
        + [{"role": "user", "content": user_content}]
    )
    raw_reply = await llm.chat(messages, max_tokens=max_tokens, output="teacher", user=user)
    parsed = llm_parse.parse_teacher_reply(raw_reply)
    parsed["corrections"] = _filter_corrections(parsed["corrections"], shown)

    session["history"].append({"role": "user", "content": user_content})
    session["history"].append({"role": "assistant", "content": parsed["reply"]})
    session["turns"] += 1
    turn_idx = session["turns"]

    audio_url = None
    if synthesize:
        audio_url, warn = await _synthesize_turn(session_id, session, parsed["reply"], turn_idx)
        if warn:
            parsed.setdefault("warnings", []).append(warn)

    memory.append_turn(
        user,
        lang,
        mode,
        {
            "transcript": shown,
            "reply": parsed["reply"],
            "corrections": parsed["corrections"],
            "new_vocab": parsed["new_vocab"],
            "suggested_followup": parsed["suggested_followup"],
        },
        label=label or session.get("label"),
        session_id=session_id,
    )

    return {
        "session_id": session_id,
        "turn": turn_idx,
        "transcript": shown,
        "reply": parsed["reply"],
        "corrections": parsed["corrections"],
        "new_vocab": parsed["new_vocab"],
        "suggested_followup": parsed["suggested_followup"],
        "revised": parsed.get("revised", ""),
        "audio_url": audio_url,
    }


# ---------------------------------------------------------------------------
# Weekly review (pushed at the start of a mode 1 session)
# ---------------------------------------------------------------------------
def weekly_review_due(user: str, lang: str) -> bool:
    """A weekly review is due on Mondays, or after 7+ days without a session."""
    if memory.has_weekly_review_this_week(user, lang):
        return False
    today = datetime.now()
    if today.weekday() == 0:  # Monday
        return True
    last = memory.last_session_date(user, lang)
    return last is not None and (today.date() - last).days >= 7


async def weekly_review_opening(session_id: str, session: dict) -> dict:
    """Generate the weekly report as the opening (mode 1 push) and persist it."""
    user, lang = session["user"], session["lang"]
    review_prompt = prompt_builder.build_mode6_prompt(
        user, lang, "weekly_review", memory.build_memory_block(user, lang)
    )
    original = session["system_prompt"]
    session["system_prompt"] = review_prompt  # only for this opening
    opening = await teacher_turn(
        session_id, session, KICKOFF_INSTRUCTION, transcript="(weekly review)"
    )
    session["system_prompt"] = original  # the rest of the session stays in mode 1
    memory.write_weekly_review(user, lang, opening["reply"])
    return {**opening, "transcript": ""}


# ---------------------------------------------------------------------------
# Mode 4: generating the text to read aloud
# ---------------------------------------------------------------------------
async def generate_reading(user: str, lang: str, topic: str) -> str:
    """Generate a text in `lang` at the learner's level, to be read aloud."""
    lang_name = config.LANG_NAMES.get(lang, lang)
    cefr = memory.read_user_cefr(user, lang)
    prompt = (
        f"Write a text in {lang_name} of about {config.READ_GEN_WORDS} words "
        f"for a {cefr} learner who is going to read it ALOUD. "
        f"Topic: {topic}.\n"
        "Natural, clear sentences of medium length. No lists, no markdown, no "
        "titles, no unusual typographic quotes. Return ONLY the text, nothing else."
    )
    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=config.READ_GEN_MAX_TOKENS,
        user=user,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    return text[: config.READ_MAX_CHARS]


# ---------------------------------------------------------------------------
# Mode 5: writing (teacher feedback or the colleague's reply)
# ---------------------------------------------------------------------------
async def writing_turn(session_id: str, session: dict, draft: str, action: str) -> dict:
    """Mode 5 turn: teacher feedback or a reply from the simulated colleague."""
    user, lang = session["user"], session["lang"]
    sub_mode, slug, subject = session["sub_mode"], session["slug"], session["subject"]

    if action == "send":
        # The final draft joins the thread and the colleague (its own persona) replies.
        thread = session["thread"]
        thread.append({"role": "user", "content": draft})
        messages = [{"role": "system", "content": session["colleague_prompt"]}, *thread]
        raw = await llm.chat(messages, max_tokens=config.AI_MAX_TOKENS_COLLEAGUE, user=user)
        reply = raw.strip()
        if reply.startswith("```"):
            reply = reply.strip("`").strip()
        thread.append({"role": "assistant", "content": reply})

        now = datetime.now().strftime("%H:%M")
        name = prompt_builder.user_display_name(user)
        memory.append_writing(user, lang, sub_mode, slug, subject, f"### {name} ({now})\n{draft}")
        memory.append_writing(
            user, lang, sub_mode, slug, subject, f"### Colleague ({now})\n{reply}"
        )

        session["turns"] += 1
        turn_idx = session["turns"]
        audio_url, _ = await _synthesize_turn(session_id, session, reply, turn_idx)

        memory.append_turn(
            user,
            lang,
            5,
            {
                "transcript": draft,
                "reply": reply,
                "corrections": [],
                "new_vocab": [],
                "suggested_followup": "",
            },
            label=f"{session.get('label')} · sent to colleague",
            session_id=session_id,
        )
        return {
            "session_id": session_id,
            "turn": turn_idx,
            "transcript": draft,
            "reply": reply,
            "corrections": [],
            "new_vocab": [],
            "suggested_followup": "",
            "revised": "",
            "audio_url": audio_url,
        }

    # action == "feedback" (mode 5 default): the teacher corrects the draft. The
    # colleague's last message is given as context to judge whether it fits.
    last_colleague = next(
        (m["content"] for m in reversed(session["thread"]) if m["role"] == "assistant"),
        "",
    )
    if last_colleague:
        user_content = f"[Colleague's last message]\n{last_colleague}\n\n[My draft reply]\n{draft}"
    else:
        user_content = f"[My draft]\n{draft}"
    return await teacher_turn(
        session_id,
        session,
        user_content,
        transcript=draft,
        synthesize=False,  # writing is text to text, no autoplay
        max_tokens=config.AI_MAX_TOKENS_FEEDBACK,
        label=f"{session.get('label')} · feedback",
    )


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------
def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def voice_opts(session: dict) -> dict:
    """Voice and speaking rate the learner picked for this session (if any)."""
    return {
        "voice": session.get("voice"),
        "length_scale": session.get("speech_rate"),
    }


async def synth_chunk(
    session_id: str,
    turn_idx: int,
    chunk_idx: int,
    text: str,
    lang: str,
    voice: str | None = None,
    length_scale: float | None = None,
):
    """Synthesize one sentence and write it to disk. Returns (url, warning).

    Without TTS for the language it returns (None, None) silently.
    """
    if not tts.configured(lang):
        return None, None
    try:
        wav = await tts.synthesize(text, lang, voice=voice, length_scale=length_scale)
        out_dir = config.AUDIO_ROOT / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{turn_idx:03d}-{chunk_idx:02d}.wav"
        (out_dir / name).write_bytes(wav)
        return f"/audio/{session_id}/{name}", None
    except Exception as exc:  # TTS must never break the turn
        return None, f"tts_failed: {exc}"


def _stream_error(exc: Exception) -> dict:
    if isinstance(exc, AIServiceError):
        return {"type": "error", "detail": exc.message, "code": exc.code, "service": exc.service}
    return {
        "type": "error",
        "detail": "The chat model stream failed.",
        "code": "stream_failed",
        "service": "chat",
    }


async def teacher_turn_stream(
    session_id: str,
    session: dict,
    user_content: str,
    transcript: str,
    on_complete: Callable[[dict], None] | None = None,
):
    """SSE generator for a conversational turn with streaming + per-sentence TTS.

    Emits: transcript -> audio* -> meta -> done (or an error event). Persistence
    (history, memory) happens when the stream closes, as in `teacher_turn`.
    `on_complete(parsed)` is only called when the turn completes successfully
    (used by the deferred kickoff of the mode 6 weekly review).
    """
    user, lang, mode = session["user"], session["lang"], session["mode"]
    t_turn = time.perf_counter()

    yield sse({"type": "transcript", "text": transcript})

    messages = (
        [{"role": "system", "content": session["system_prompt"]}]
        + session["history"]
        + [{"role": "user", "content": user_content}]
    )

    session["turns"] += 1
    turn_idx = session["turns"]
    extractor = ReplyStreamExtractor(min_chunk_chars=config.TTS_CHUNK_MIN_CHARS)
    chunk_idx = 0
    audio_urls: list[str] = []
    warnings: list[str] = []
    t_first_audio: float | None = None
    persisted = False

    def _persist(parsed: dict) -> None:
        """History + memory, same contract as the blocking turn. Only once."""
        nonlocal persisted
        if persisted:
            return
        persisted = True
        session["history"].append({"role": "user", "content": user_content})
        session["history"].append({"role": "assistant", "content": parsed["reply"]})
        memory.append_turn(
            user,
            lang,
            mode,
            {
                "transcript": transcript,
                "reply": parsed["reply"],
                "corrections": parsed["corrections"],
                "new_vocab": parsed["new_vocab"],
                "suggested_followup": parsed["suggested_followup"],
            },
            label=session.get("label"),
            session_id=session_id,
        )

    try:
        try:
            # A missing chat model raises AIServiceError on the first iteration,
            # inside this try, so it becomes an error event instead of a crash.
            async for delta in llm.chat_stream(
                messages,
                max_tokens=config.AI_MAX_TOKENS,
                output="teacher",
                user=user,
            ):
                for sentence in extractor.feed(delta):
                    chunk_idx += 1
                    url, warn = await synth_chunk(
                        session_id, turn_idx, chunk_idx, sentence, lang, **voice_opts(session)
                    )
                    if warn:
                        warnings.append(warn)
                    if url:
                        audio_urls.append(url)
                        if t_first_audio is None:
                            t_first_audio = time.perf_counter()
                    yield sse({"type": "audio", "url": url, "text": sentence})
        except Exception as exc:
            if isinstance(exc, AIServiceError):
                logger.warning("[turn-stream] chat stream failed: %s", exc.message)
            else:
                logger.exception("[turn-stream] chat stream failed")
            yield sse(_stream_error(exc))
            session["turns"] -= 1  # aborted turn, does not count
            persisted = True  # nothing to save in the finally
            return

        raw = extractor.raw
        # Pending tail of the reply (last sentence under the threshold, or a reply
        # without any sentence boundary).
        tail = extractor.finish()
        if tail:
            chunk_idx += 1
            url, warn = await synth_chunk(
                session_id, turn_idx, chunk_idx, tail, lang, **voice_opts(session)
            )
            if warn:
                warnings.append(warn)
            if url:
                audio_urls.append(url)
                if t_first_audio is None:
                    t_first_audio = time.perf_counter()
            yield sse({"type": "audio", "url": url, "text": tail})

        parsed = llm_parse.parse_teacher_reply(raw)
        parsed["corrections"] = _filter_corrections(parsed["corrections"], transcript)

        # Fallback: the model gave no JSON with `reply`, so no audio went out.
        # Synthesize the whole raw text at once so the turn is not silent.
        if not extractor.found_reply and parsed["reply"]:
            chunk_idx += 1
            url, warn = await synth_chunk(
                session_id, turn_idx, chunk_idx, parsed["reply"], lang, **voice_opts(session)
            )
            if warn:
                warnings.append(warn)
            if url:
                audio_urls.append(url)
                if t_first_audio is None:
                    t_first_audio = time.perf_counter()
            yield sse({"type": "audio", "url": url, "text": parsed["reply"]})

        _persist(parsed)
        if on_complete is not None:
            try:
                on_complete(parsed)
            except Exception:
                logger.exception("[turn-stream] on_complete failed for turn %d", turn_idx)

        yield sse(
            {
                "type": "meta",
                "turn": turn_idx,
                "transcript": transcript,
                "reply": parsed["reply"],
                "corrections": parsed["corrections"],
                "new_vocab": parsed["new_vocab"],
                "suggested_followup": parsed["suggested_followup"],
                "revised": parsed.get("revised", ""),
                "audio_urls": audio_urls,
                "warnings": warnings,
            }
        )
        yield sse({"type": "done"})

        total_ms = (time.perf_counter() - t_turn) * 1000
        first_ms = int((t_first_audio - t_turn) * 1000) if t_first_audio else -1
        logger.info(
            "[turn-stream] user=%s lang=%s mode=%d turn=%d first_audio=%dms total=%dms chunks=%d",
            user,
            lang,
            mode,
            turn_idx,
            first_ms,
            int(total_ms),
            len(audio_urls),
        )
    finally:
        # Client disconnected mid-stream (barge-in, app closed, network): the
        # generator closes (GeneratorExit/CancelledError) without reaching
        # _persist. Save what the teacher managed to say so history and turn_idx
        # stay consistent (otherwise the next turn reuses the index and overwrites
        # its WAVs). No awaits here: only parsing and synchronous I/O.
        if not persisted:
            partial = (
                llm_parse.parse_teacher_reply(extractor.raw) if extractor.raw.strip() else None
            )
            if partial and partial["reply"]:
                logger.info(
                    "[turn-stream] client cut turn %d midway: persisting the partial reply",
                    turn_idx,
                )
                _persist(partial)
            else:
                session["turns"] -= 1  # there was no turn after all
