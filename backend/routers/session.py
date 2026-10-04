"""Session lifecycle: /session/start, /session/end, /profiles, /scenarios, /voices."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import books, config, memory, minimal_pairs, prompt_builder, scenarios, syllabus
from ..cefr import next_cefr
from ..post_session import finalize_session, save_session_notes
from ..schemas import SessionEndResult, SessionStartResult
from ..services import AIServiceError, llm, tts
from ..sessions import SESSIONS, purge_session_audio, validate_ids
from ..teacher import (
    KICKOFF_EXPRESSIONS,
    KICKOFF_INSTRUCTION,
    generate_reading,
    synth_chunk,
    teacher_turn,
    weekly_review_due,
    weekly_review_opening,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# References to fire-and-forget tasks, so they are not garbage-collected early.
_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ---------------------------------------------------------------------------
# /profiles  (available learners + the languages they study)
# ---------------------------------------------------------------------------
@router.get("/profiles")
def list_profiles() -> dict:
    """List the available profiles by reading <DATA_DIR>/<user>/profile.md."""
    profiles: list[dict] = []
    if not config.DATA_DIR.is_dir():
        return {"profiles": profiles}
    for child in sorted(config.DATA_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        path = child / "profile.md"
        if not path.is_file():
            continue
        data = memory.parse_frontmatter(path.read_text(encoding="utf-8"))
        studied_raw = data.get("languages_studied") or []
        if isinstance(studied_raw, str):
            studied_raw = [studied_raw]
        studied = [code for code in studied_raw if code in config.SUPPORTED_LANGS]
        primary = data.get("primary_language") or (studied[0] if studied else None)
        if not primary or primary not in config.SUPPORTED_LANGS:
            continue
        # Languages actually STARTED: the ones that already have a data folder.
        # Not the same as languages_studied (what profile.md declares): any learner
        # can start any language, so the declared list falls short.
        started = sorted(
            d.name for d in child.iterdir() if d.is_dir() and d.name in config.SUPPORTED_LANGS
        )
        profiles.append(
            {
                "user": child.name,
                "name": prompt_builder.user_display_name(child.name),
                "primary_language": primary,
                "languages_studied": studied,
                "languages_started": started,
                "ui_language": data.get("ui_language", "en"),
            }
        )
    return {"profiles": profiles}


class ProfileCreateReq(BaseModel):
    name: str
    target_language: str
    # Why the learner wants the language, in their own words. It goes into
    # USER.md, which the teacher reads on every turn.
    goals: str = ""
    ui_language: str = "en"


@router.post("/profiles", status_code=201)
def create_profile(req: ProfileCreateReq) -> dict:
    """Create a learner: <DATA_DIR>/<slug>/profile.md plus <lang>/USER.md.

    The level is left empty on purpose: it is measured by the initial
    assessment, never guessed.
    """
    name = " ".join(req.name.split())[:40]
    if not name:
        raise HTTPException(400, "name is required")
    lang = req.target_language
    if lang not in config.SUPPORTED_LANGS:
        raise HTTPException(400, f"Unsupported target_language: {lang!r}")
    ui = req.ui_language if req.ui_language in config.UI_LANG_NAMES else "en"
    user = memory.slugify(name, max_len=24).replace("-", "_")
    if user == "untitled":
        raise HTTPException(400, "name must contain at least one letter or digit")
    root = config.DATA_DIR / user
    if (root / "profile.md").exists():
        raise HTTPException(409, f"a learner called {name!r} already exists")
    root.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace("\n", " ").replace(":", " ")
    (root / "profile.md").write_text(
        "---\n"
        f"name: {safe_name}\n"
        f"languages_studied: [{lang}]\n"
        f"primary_language: {lang}\n"
        f"ui_language: {ui}\n"
        "stt_hints: []\n"
        "---\n"
        f"# {safe_name}\n",
        encoding="utf-8",
    )
    goals = req.goals.strip() or "(not written yet)"
    (memory.user_lang_dir(user, lang) / "USER.md").write_text(
        "---\n"
        "cefr_estimate:\n"
        "---\n"
        f"# {safe_name} learning {config.LANG_NAMES[lang]}\n\n"
        f"## Why I am learning it\n{goals}\n",
        encoding="utf-8",
    )
    return {"user": user, "name": safe_name, "primary_language": lang}


# ---------------------------------------------------------------------------
# /scenarios  (role-play library for the mode 2 picker)
# ---------------------------------------------------------------------------
@router.get("/scenarios")
def list_scenarios() -> dict:
    return {"scenarios": scenarios.list_scenarios()}


# ---------------------------------------------------------------------------
# /session/start
# ---------------------------------------------------------------------------
class SessionStartReq(BaseModel):
    user_id: str
    target_language: str
    mode: int = 1
    scenario: str | None = None  # mode 2: "work/kpi-meeting"
    context: str | None = None  # mode 3 / mode 4 / mode 8: the pasted text
    sub_mode: str | None = None  # mode 5: "email" | "chat"; mode 6: assessment|weekly_review|test
    subject: str | None = None  # mode 5: subject / modes 3-4: optional title
    generate: bool = False  # mode 4: generate the text instead of pasting it
    topic: str | None = None  # mode 4: topic to generate / mode 7: theme
    # Modes with an opening (2, 3, 6, 7, 9): if true the blocking opening does NOT
    # run; the frontend requests it streamed via /turn/stream kickoff=1.
    defer_opening: bool = False
    # TTS voice picked for the session (an id from config.LANGUAGES[lang]["voices"]).
    voice: str | None = None
    # Initial speaking rate (length_scale; see config.SPEECH_RATES).
    speech_rate: float | None = None
    # Mode 8 (book): the book being read + the page number about to be read.
    book_slug: str | None = None
    page: int | None = None
    # Mode 9 (lesson): syllabus topic. If missing, syllabus.next_topic is used.
    topic_id: str | None = None
    # Mode 4 (minimal pairs): start a pairs exercise instead of reading a text.
    # No reference_text and no chat model.
    pair_mode: bool = False


def _read_expressions_seed(lang: str) -> str:
    """Curated seed of native expressions for the language (prompts/expressions/<lang>.md).

    Versioned teaching content, not personal data. It goes into mode 7 whole (it
    is short) so the teacher favours the ones that fit the theme and the learner
    does not know yet.
    """
    path = config.PROMPTS_ROOT / "expressions" / f"{lang}.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    # Strip the frontmatter, if any.
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.strip()


def _clamp_rate(rate: float | None) -> float | None:
    """Safe length_scale: clamped to [0.7, 1.6] (None = normal)."""
    if rate is None or rate == 1.0:
        return None
    return max(0.7, min(1.6, float(rate)))


@router.get("/voices")
def list_voices() -> dict:
    """Voices per language + speaking rates, for the frontend picker."""
    return {
        "voices": {
            code: [{"id": v, "label": v} for v in spec["voices"]]
            for code, spec in config.LANGUAGES.items()
        },
        # Catalogue of supported languages. The frontend offers ALL of them to any
        # learner: validate_ids only requires the language to be in
        # SUPPORTED_LANGS, and memory.py creates the folder on demand. Derived from
        # config.LANGUAGES: adding a language there is enough.
        "languages": [
            {"code": code, "name": spec["name"]} for code, spec in config.LANGUAGES.items()
        ],
        "rates": config.SPEECH_RATES,
    }


@router.post("/session/start", response_model=SessionStartResult)
async def session_start(req: SessionStartReq):
    user, lang, mode = req.user_id, req.target_language, req.mode
    validate_ids(user, lang)
    if mode not in config.SUPPORTED_MODES:
        raise HTTPException(400, f"unsupported mode: {mode} (available: {config.SUPPORTED_MODES})")

    extra_block: str | None = None
    scenario_info: dict | None = None
    label: str | None = None
    extra_state: dict = {}

    if mode == 2:
        if not req.scenario:
            raise HTTPException(400, "mode 2 requires 'scenario' (e.g. work/kpi-meeting)")
        try:
            extra_block, scenario_info = scenarios.build_block(req.scenario, lang)
        except scenarios.ScenarioNotFound:
            raise HTTPException(404, f"unknown scenario: {req.scenario!r}") from None
        label = req.scenario
    elif mode == 3:
        text = (req.context or "").strip()
        if not text:
            raise HTTPException(400, "mode 3 requires 'context' (the pasted text)")
        if re.fullmatch(r"https?://\S+", text):
            raise HTTPException(400, "paste the text of the article, not its URL")
        truncated = len(text) > config.READING_MAX_CHARS
        if truncated:
            text = text[: config.READING_MAX_CHARS]
        title = (req.subject or "").strip()
        slug = memory.slugify(title or text[:60])
        reading_file = memory.write_reading(user, lang, slug, title, text, truncated)
        extra_block = "## Working text\n\n" + text
        label = f"reading: {reading_file}"
    elif mode == 4:
        if req.pair_mode:
            # Minimal pairs: no reference text and no chat model.
            picked = minimal_pairs.pick_pairs(user, lang, n=config.PAIRS_PER_SESSION)
            if not picked:
                raise HTTPException(500, f"empty minimal pairs seed for {lang!r}")
            session_id_tmp = uuid.uuid4().hex[:12]  # for the audio urls
            enriched = []
            for i, p in enumerate(picked):
                urls = []
                for j, w in enumerate(p["words"]):
                    # None when TTS is not configured: the browser speaks instead.
                    url, _ = await synth_chunk(
                        session_id_tmp,
                        0,
                        i * 2 + j + 1,
                        w,
                        lang,
                        voice=req.voice if req.voice in tts.allowed_voices(lang) else None,
                    )
                    urls.append(url)
                enriched.append({**p, "audio_urls": urls})
            label = "minimal pairs"
            extra_state = {
                "pairs": enriched,
                "pair_results": [],
                "forced_session_id": session_id_tmp,
            }
            # No reference_text: the pairs UI does not use the reading view.
        elif req.generate:
            topic = (req.topic or "").strip()
            if not topic:
                raise HTTPException(400, "mode 4 with generate requires 'topic'")
            reference_text = await generate_reading(user, lang, topic)
            title = topic
            if not reference_text:
                raise HTTPException(422, "could not get a text to read")
            slug = memory.slugify(title or reference_text[:60])
            reading_file = memory.write_reading(
                user, lang, slug, title, reference_text, truncated=False
            )
            label = f"read aloud: {reading_file}"
            extra_state = {"reference_text": reference_text}
        else:
            reference_text = (req.context or "").strip()
            if not reference_text:
                raise HTTPException(
                    400, "mode 4 requires 'context' (the text to read) or generate+topic"
                )
            if re.fullmatch(r"https?://\S+", reference_text):
                raise HTTPException(400, "paste the text to read, not its URL")
            reference_text = reference_text[: config.READ_MAX_CHARS]
            title = (req.subject or "").strip()
            if not reference_text:
                raise HTTPException(422, "could not get a text to read")
            slug = memory.slugify(title or reference_text[:60])
            reading_file = memory.write_reading(
                user, lang, slug, title, reference_text, truncated=False
            )
            label = f"read aloud: {reading_file}"
            extra_state = {"reference_text": reference_text}
    elif mode == 5:
        sub_mode = (req.sub_mode or "email").strip()
        if sub_mode not in ("email", "chat"):
            raise HTTPException(400, f"invalid sub_mode: {sub_mode!r} (email|chat)")
        subject = (req.subject or "").strip()
        slug = memory.slugify(subject) if subject else "thread"
        kind = "formal email" if sub_mode == "email" else "informal team chat"
        extra_block = f"## Writing context\n- Thread type: {kind}.\n" + (
            f"- Subject: {subject}\n" if subject else ""
        )
        label = f"writing {sub_mode}" + (f": {slug}" if subject else "")
        extra_state = {
            "sub_mode": sub_mode,
            "subject": subject,
            "slug": slug,
            "colleague_prompt": prompt_builder.build_colleague_prompt(
                user, lang, sub_mode, subject
            ),
            "thread": [],  # the real exchange (sent drafts + replies)
        }
    elif mode == 6:
        sub = (req.sub_mode or "assessment").strip()
        if sub not in ("assessment", "weekly_review", "test"):
            raise HTTPException(
                400, f"invalid mode 6 sub_mode: {sub!r} (assessment|weekly_review|test)"
            )
        label = f"mode 6 · {sub}"
        extra_state = {"sub_mode": sub}
        if sub == "test":
            cur_cefr = memory.read_user_cefr(user, lang)
            target = next_cefr(cur_cefr) or cur_cefr
            extra_block = (
                f"## Test context\n- Current level: {cur_cefr}\n- Target level: {target}\n"
            )
            extra_state["target_cefr"] = target
    elif mode == 7:
        # Native expressions: a free theme (topic) or "surprise me" (no topic).
        theme = (req.topic or "").strip()
        seed = _read_expressions_seed(lang)
        learned = memory.read_expressions(user, lang)
        parts = []
        if theme:
            parts.append(f"## Today's theme\n{theme}")
        else:
            parts.append(
                "## Today's theme\nFree (surprise me): pick varied, useful everyday "
                "expressions, without sticking to a single context."
            )
        if seed:
            parts.append(
                "## Expression seed\n"
                "Prefer these if they fit the theme and the learner does not know them yet. "
                "You may add others that a native speaker really uses.\n\n" + seed
            )
        if learned.strip():
            parts.append("## Already covered (do NOT reintroduce them as new)\n" + learned)
        extra_block = "\n\n".join(parts)
        label = f"expressions: {theme or 'surprise me'}"
    elif mode == 8:
        if not req.book_slug or not books.valid_slug(req.book_slug):
            raise HTTPException(400, "mode 8 requires a valid 'book_slug'")
        book = books.read_book(user, lang, req.book_slug)
        if book is None:
            raise HTTPException(404, f"book not found: {req.book_slug!r}")
        text = (req.context or "").strip()
        if not text:
            raise HTTPException(400, "mode 8 requires 'context' (the page text after OCR)")
        text = text[: config.BOOK_MAX_CHARS]
        page = int(req.page or (book["page"] + 1))
        summary = book["summary"] or "(first session: no summary yet)"
        extra_block = (
            "## Book in progress\n"
            f"- Title: {book['title']}\n"
            f"- Page just read aloud: {page}\n"
            f"- Plot summary so far:\n{summary}\n\n"
            "## Page text\n\n" + text
        )
        label = f"book: {req.book_slug} · p.{page}"
        extra_state = {
            "book_slug": req.book_slug,
            "book_page": page,
            "reference_text": text,
        }
    elif mode == 9:
        topic_id = (req.topic_id or "").strip() or None
        lesson = (
            syllabus.topic_by_id(lang, topic_id) if topic_id else syllabus.next_topic(user, lang)
        )
        if lesson is None:
            raise HTTPException(
                status_code=400,
                detail="unknown topic_id or syllabus completed",
            )
        status = (
            syllabus.read_user_syllabus(user, lang).get(lesson["id"], {}).get("status", "pending")
        )
        key_points = "\n".join(f"- {p}" for p in lesson["key_points"])
        examples = "\n".join(f"- {e}" for e in lesson["examples"])
        extra_block = (
            f"## Today's lesson: {lesson['title']} ({lesson['id']})\n\n"
            f"The learner's status on this lesson: {status} "
            f"(previous sessions: {syllabus.topic_session_count(user, lang, lesson['id'])}).\n\n"
            f"**Grammar**: {lesson['grammar']}\n\n"
            f"**Goal**: {lesson['goal']}\n\n"
            f"**Key points**:\n{key_points}\n\n"
            f"**Anchor examples** (use them and create variations):\n{examples}\n\n"
            f"**Suggested practice**: {lesson['practice']}\n"
        )
        syllabus.set_topic_status(user, lang, lesson["id"], "seen")
        label = f"lesson: {lesson['id']}"
        extra_state = {"topic_id": lesson["id"]}

    memory_block = memory.build_memory_block(user, lang)
    if mode == 6:
        system_prompt = prompt_builder.build_mode6_prompt(
            user, lang, extra_state["sub_mode"], memory_block, extra_block
        )
    else:
        system_prompt = prompt_builder.build_system_prompt(
            user, lang, mode, memory_block, extra_block
        )

    # Minimal pairs pre-synthesize audio under a temporary id; the real
    # session_id is forced to that id so the /audio/<id>/... urls match.
    session_id = extra_state.pop("forced_session_id", None) or uuid.uuid4().hex[:12]
    # Diagnostic log: which voice the frontend sent. If it sent none, req.voice
    # is None and the language default applies; this separates "the frontend did
    # not persist the choice" from "the backend loses it".
    logger.info(
        "[session-start] user=%s lang=%s mode=%d voice=%r speech_rate=%r defer=%r",
        user,
        lang,
        mode,
        req.voice,
        req.speech_rate,
        req.defer_opening,
    )
    session = {
        "id": session_id,
        "user": user,
        "lang": lang,
        "mode": mode,
        "system_prompt": system_prompt,
        "history": [],  # user/assistant turns in natural language
        "started_at": datetime.now().isoformat(timespec="seconds"),
        # Day of the session file: the closing passes use it so they do not read
        # the wrong day if the session is finalized after midnight.
        "day": datetime.now().strftime("%Y-%m-%d"),
        "last_activity": time.monotonic(),
        # The learner's voice settings (None = language defaults).
        "voice": req.voice if req.voice in tts.allowed_voices(lang) else None,
        "speech_rate": _clamp_rate(req.speech_rate),
        "turns": 0,
        # "Conversation already opened" flag: the /turn/stream kickoff is only
        # allowed while it is False. Mode 8 reaches the kickoff with turns > 0
        # (reading aloud scores turns), so looking at turns is not enough.
        "opened": False,
        "label": label,
        **extra_state,
    }
    SESSIONS[session_id] = session

    opening = None
    weekly_review = False
    opening_pending = False
    if mode in (2, 3, 6, 7, 9):
        # The teacher opens: the scene (2), the text (3), assessment/review/test
        # (6), the first native expression (7) or the lesson's first exercise (9).
        if req.defer_opening:
            # Deferred opening: the frontend requests it streamed with
            # /turn/stream kickoff=1 (first audio in seconds instead of waiting for
            # the whole reply). Background warmup: the full system prompt
            # (including the extra block, e.g. a book page) gets into the prompt
            # cache WHILE the learner reviews the OCR or picks a scenario, so the
            # kickoff does not pay the whole prefill.
            _background(llm.warmup(system_prompt, user=user))
            opening_pending = True
        else:
            # The call itself loads the model, so it replaces the warmup.
            opening = await teacher_turn(
                session_id,
                session,
                KICKOFF_EXPRESSIONS if mode == 7 else KICKOFF_INSTRUCTION,
                transcript="(teacher opening)",
            )
            opening = {**opening, "transcript": ""}
            session["opened"] = True
            if mode == 6 and session.get("sub_mode") == "weekly_review":
                memory.write_weekly_review(user, lang, opening["reply"])
    elif mode == 1 and weekly_review_due(user, lang):
        # Weekly review push: the teacher opens with the report instead of the
        # usual greeting. The rest of the session stays in mode 1.
        opening = await weekly_review_opening(session_id, session)
        weekly_review = True
    elif mode != 4:
        # Modes 1 and 5: warm up and CACHE the system prompt prefix in the
        # background; the first turn reuses the cache and skips the prefill.
        # Mode 4 does not converse, so it needs no conversational warmup.
        _background(llm.warmup(system_prompt, user=user))

    return {
        "session_id": session_id,
        "user": user,
        "target_language": lang,
        "mode": mode,
        "scenario_info": scenario_info,
        "opening": opening,
        "reference_text": session.get("reference_text"),
        "weekly_review": weekly_review,
        "opening_pending": opening_pending,
        "pairs": session.get("pairs"),
    }


# ---------------------------------------------------------------------------
# /session/end
# ---------------------------------------------------------------------------
class SessionEndReq(BaseModel):
    session_id: str
    # Mode 8: the page where the learner really stopped. Without it the START page
    # would be stored, which is wrong as soon as "Add another page" is used.
    # Optional on purpose: clients that do not send it keep the old behaviour.
    end_page: int | None = None


@router.post("/session/end", response_model=SessionEndResult)
async def session_end(req: SessionEndReq):
    # Atomic pop: two nearly simultaneous closes (pagehide beacon + effect
    # cleanup) must not finalize the same session twice (duplicate progress).
    session = SESSIONS.pop(req.session_id, None)
    if not session:
        raise HTTPException(404, "unknown or already closed session_id")
    # 0 or negative is ignored: it must not erase the book's real progress.
    if req.end_page and req.end_page > 0 and session.get("book_slug"):
        session["book_page"] = int(req.end_page)
    try:
        result = await finalize_session(session)
    except AIServiceError as exc:
        # The session is already closed and every turn is in the session log;
        # only the end-of-session analysis is lost. Say so instead of failing.
        logger.warning("[session-end] analysis skipped: %s", exc.message)
        result = {"analysis_error": exc.message}
        save_session_notes(session, result)
    finally:
        purge_session_audio(req.session_id)
    turns = session["turns"]
    return {"closed": req.session_id, "turns": turns, **result}
