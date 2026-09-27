"""End-of-session passes (analyst model calls): progress, vocabulary or
expressions, skill tracker, initial assessment and level-up test.

These passes do NOT use the teacher reply contract: they have their own JSON
formats, and the retry in `_analyst_json` is the safety net.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from . import books, config, llm_parse, memory, srs, syllabus
from .cefr import cefr_baseline, next_cefr
from .services import llm

logger = logging.getLogger(__name__)

_SUPPORT = config.UI_LANG_NAMES[config.SUPPORT_LANG]

# Turns labelled "read aloud" or "minimal pairs" are the learner reading fixed
# words or text; their transcript is recognizer output, not learner production.
_SUMMARY_INSTRUCTION = (
    "You are a teaching analyst. From the transcript of a conversation session, "
    "write a summary for the learner's history. Answer ONLY with a valid JSON "
    "object, no extra text and no ```:\n"
    "{\n"
    f'  "progress_note": "3-5 bullet points in {_SUPPORT}: recurring mistakes, what '
    'improved, what to work on next. Use dashes, one idea per line.",\n'
    '  "vocab": [{"term": "...", "translation": "...", "example": "..."}],\n'
    '  "missed_opportunities": ["2-4 words or phrases in the target language that the '
    f"learner COULD have used and did not (with a short {_SUPPORT} translation in "
    'parentheses). Only if they really fit what the learner meant to say; [] otherwise."]\n'
    "}\n"
    "vocab: consolidate only the useful vocabulary of the session (may be []). "
    f"translation in {_SUPPORT}, term and example in the target language.\n"
    "IMPORTANT: turns labelled 'read aloud' (modes 4 and 8) or 'minimal pairs' "
    "(mode 4) are the learner reading fixed words or text aloud; use them ONLY as "
    "evidence of pronunciation and fluency. "
    "Do NOT extract new vocabulary or grammar/spelling mistakes from those turns: "
    "the words are not the learner's own production and may be transcription errors "
    "of the speech recognizer.\n"
    f"Write progress_note and every translation in {_SUPPORT}, even though these "
    "instructions are in English."
)


_EXPRESSIONS_INSTRUCTION = (
    "You are a teaching analyst. From the transcript of a 'native expressions' "
    "session, extract the idiomatic expressions the teacher worked on with the "
    "learner in this session. Answer ONLY with a valid JSON object, no extra text "
    "and no ```:\n"
    "{\n"
    f'  "progress_note": "2-4 bullet points in {_SUPPORT}: what was covered, how well '
    'the learner used them, what to reinforce. One idea per line with dashes.",\n'
    '  "expressions": [{"expression": "the expression in the target language", '
    f'"meaning": "what it really means, in {_SUPPORT}", "register": "colloquial, '
    'formal or regional if relevant; empty otherwise", "example": "example sentence '
    'in the target language"}]\n'
    "}\n"
    "expressions: only the ones really worked on in this session (may be []). Do not "
    "include loose vocabulary or words without idiomatic character (greetings, normal "
    "questions and everyday words do NOT count). If no real idiomatic expression was "
    "worked on in the session, return an empty list."
)


_LESSON_EXTRA = (
    ' Also assess the syllabus lesson: return "topic_status" with one of'
    ' "seen" | "practiced" | "mastered", with a CONSERVATIVE criterion:'
    ' "practiced" only if the learner solved most exercises with little help;'
    ' "mastered" only if the topic had already been practiced before (previous'
    " sessions are listed in the system prompt) and this time it went clearly"
    " smoothly. When in doubt, repeat the current status."
)


def _norm_expressions(raw) -> list[dict]:
    """Normalize the expression list of the mode 7 summary."""
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        expr = str(item.get("expression", "")).strip()
        if not expr:
            continue
        out.append(
            {
                "expression": expr,
                "meaning": str(item.get("meaning", "")).strip(),
                "register": str(item.get("register", "")).strip(),
                "example": str(item.get("example", "")).strip(),
            }
        )
    return out


async def _analyst_json(
    instruction: str,
    payload: str,
    *,
    max_tokens: int,
    label: str,
    temperature: float = 0.2,
    user: str | None = None,
) -> dict:
    """Call the chat model for an auxiliary pass that must return a JSON object.

    These passes persist progress, the tracker and the assessment: losing the
    answer to format drift is expensive (the assessment happens once), so if it
    does not parse it is retried ONCE with a reminder of the contract; if that
    fails too the raw answer is logged and the result degrades to {} (callers
    already tolerate missing fields)."""
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": payload},
    ]
    raw = await llm.chat(
        messages, temperature=temperature, max_tokens=max_tokens, output="json", user=user
    )
    data = llm_parse.extract_json_object(raw)
    if data is not None:
        return data
    logger.warning("[%s] non-JSON answer from the model, retrying: %.300s", label, raw)
    retry = [
        *messages,
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": "Your previous answer was not a valid JSON object. Answer now with "
            "ONLY the requested JSON object, no extra text and no ```.",
        },
    ]
    raw = await llm.chat(
        retry, temperature=temperature, max_tokens=max_tokens, output="json", user=user
    )
    data = llm_parse.extract_json_object(raw)
    if data is None:
        logger.warning("[%s] second attempt is not JSON either, discarding: %.300s", label, raw)
        return {}
    return data


def _skill_dims_text() -> str:
    return "\n".join(f"- {k}: {label}" for k, label in config.SKILL_DIMS)


async def _update_skill_tracker(session: dict) -> None:
    """Async pass: update skill-tracker.md (8 scores + errors) with the analyst."""
    user, lang = session["user"], session["lang"]
    transcript = memory.read_session_day(user, lang, session.get("day"), session.get("id"))
    if not transcript or session.get("turns", 0) == 0:
        return
    tr = memory.read_skill_tracker(user, lang)
    # Without a prior assessment no placeholder tracker is invented: the progress
    # screen shows an honest empty state until a real assessment happens. Only
    # _finalize_assessment (mode 6 · assessment) creates the tracker.
    if not tr["exists"]:
        return
    cefr = tr["cefr"] or memory.read_user_cefr(user, lang)
    base = cefr_baseline(cefr)
    current = {
        k: (tr["scores"].get(k) if tr["scores"].get(k) is not None else base)
        for k in config.SKILL_KEYS
    }
    instruction = (
        "You are a language teaching analyst. Update the learner's skill tracker "
        "from the last session. Answer ONLY with a valid JSON object, no ```:\n"
        "{\n"
        '  "scores": { ' + ", ".join(f'"{k}": <0-100>' for k in config.SKILL_KEYS) + " },\n"
        f'  "active_errors": ["recurring mistakes to work on, in {_SUPPORT}, max 6"],\n'
        '  "resolved_errors": ["mistakes overcome compared to before, max 4"],\n'
        f'  "note": "1-2 sentences in {_SUPPORT}: what changed this session"\n'
        "}\n"
        f"The 8 dimensions (key: meaning):\n{_skill_dims_text()}\n"
        "Adjust the scores CONSERVATIVELY (0 to 5 points per session unless there is "
        "strong evidence). Keep the previous active errors that still show up; move "
        "the ones that no longer do to resolved.\n"
        "IMPORTANT: turns labelled 'read aloud' (modes 4 and 8) or 'minimal pairs' "
        "(mode 4) are the learner reading fixed words or text aloud; they count ONLY "
        "for pronunciation, fluency and reading comprehension. Do NOT use them as "
        "evidence of grammar or vocabulary, and do not record odd or misspelled words "
        "that appear there as learner mistakes: they may be speech recognizer errors, "
        "not the learner's."
    )
    payload = (
        f"CEFR level: {cefr}\n"
        f"Current scores: {json.dumps(current, ensure_ascii=False)}\n"
        f"Current active errors: {tr['active_errors']}\n\n"
        f"Session transcript:\n{transcript[-6000:]}"
    )
    data = await _analyst_json(
        instruction,
        payload,
        max_tokens=600,
        label="skill-tracker",
        user=session["user"],
    )
    new_scores: dict[str, int] = {}
    for k in config.SKILL_KEYS:
        v = (data.get("scores") or {}).get(k, current[k])
        try:
            new_scores[k] = max(0, min(100, int(v)))
        except (ValueError, TypeError):
            new_scores[k] = current[k]
    active = [str(e).strip() for e in (data.get("active_errors") or []) if str(e).strip()][:6]
    resolved = [str(e).strip() for e in (data.get("resolved_errors") or []) if str(e).strip()][:4]
    if not active:
        active = tr["active_errors"]  # keep the previous ones if the model returned none
    note = str(data.get("note", "")).strip()
    memory.write_skill_tracker(
        user, lang, cefr, new_scores, active, resolved, history_note=note or None
    )


_BOOK_SUMMARY_INSTRUCTION = (
    "You are a reading assistant. The learner is reading a book page by page; you "
    "have the plot summary so far, the text of the page just read and the "
    "conversation about it. Rewrite the CUMULATIVE plot summary (not just this "
    f"page) in 3-6 sentences in {_SUPPORT}, so the teacher can pick up the thread "
    "next session. Answer ONLY with a valid JSON object, no ```:\n"
    '{ "summary": "..." }'
)


async def _update_book(session: dict) -> None:
    """Close a book session (mode 8): page + plot summary + history.

    The plot summary is only rewritten (with the model) if there was a
    comprehension conversation (`session["opened"]`). In READ-ONLY sessions there
    is nothing new to summarize: the previous summary is kept and the close runs
    without the model (fast and failure-proof). Also, a failing summary must
    NEVER block advancing the page and the history: that is why the write
    (`books.update_book`) ALWAYS comes last, outside the model's try."""
    user, lang, slug = session["user"], session["lang"], session["book_slug"]
    page = int(session.get("book_page") or 0)
    book = books.read_book(user, lang, slug)
    summary = book["summary"] if book else ""
    if session.get("opened"):
        payload = (
            f"Plot summary so far:\n{summary or '(empty)'}\n\n"
            f"Text of page {page}:\n{(session.get('reference_text') or '')[:3000]}\n\n"
            f"Session conversation (tail):\n"
            f"{memory.read_session_day(user, lang, session.get('day'), session.get('id'))[-3000:]}"
        )
        try:
            data = await _analyst_json(
                _BOOK_SUMMARY_INSTRUCTION,
                payload,
                max_tokens=400,
                label="book-summary",
                user=session["user"],
            )
            new_summary = str(data.get("summary", "")).strip()
            if new_summary:
                summary = new_summary
        except Exception:
            logger.exception("[book] failed to generate the plot summary; keeping the previous one")
    note = session.get("read_note") or ""
    acc = ""
    if "% clear" in note:
        acc = " · read aloud " + note.split("Result: ", 1)[-1].split(" clear", 1)[0]
    books.update_book(user, lang, slug, page=page, summary=summary, history_line=f"p.{page}{acc}")


def _stt_hint_keys(user: str) -> set[str]:
    """Normalized keys of the profile's `stt_hints` (proper names).

    When the speech recognizer mishears a proper name, the teacher "corrects" it
    and that false correction would end up in vocab.md as if it were a learner
    mistake. Proper names listed in the profile must never become vocabulary.
    The hints also go into the speech-to-text prompt to reduce mishearing.

    Normalized like the vocabulary dedup, so `das Bankhof` and `BANKHOF` match
    the hint `Bankhof`.
    """
    fm = memory.parse_frontmatter(memory.read_profile_root(user))
    hints = fm.get("stt_hints") or []
    if isinstance(hints, str):
        hints = [hints]
    return {key for h in hints if h and (key := memory.normalize_vocab_term(str(h)).lower())}


async def _post_session_pass(session: dict) -> dict:
    """Post-session pass: update progress.md and vocab.md (or expressions.md in
    mode 7) with the analyst, plus the skill tracker."""
    user, lang = session["user"], session["lang"]
    transcript = memory.read_session_day(user, lang, session.get("day"), session.get("id"))
    if not transcript or session["turns"] == 0:
        return {"progress_updated": False, "vocab_added": 0}

    is_expr = session.get("mode") == 7
    if is_expr:
        instruction = _EXPRESSIONS_INSTRUCTION
    elif session.get("topic_id"):
        # Mode 9 (lesson): the standard summary plus the topic assessment.
        instruction = _SUMMARY_INSTRUCTION + _LESSON_EXTRA
    else:
        instruction = _SUMMARY_INSTRUCTION
    # Cheap defence in the prompt, on top of the code filter below: the analyst
    # must not treat the learner's proper names as mistakes.
    hints = sorted(_stt_hint_keys(user))
    if hints:
        instruction += (
            " Note that these words are proper names from the learner's life"
            f" and NEVER mistakes or vocabulary: {', '.join(hints)}."
        )
    data = await _analyst_json(
        instruction,
        transcript[-6000:],
        max_tokens=500,
        label="session-summary",
        user=session["user"],
    )

    note_raw = data.get("progress_note", "")
    if isinstance(note_raw, list):
        # The model sometimes returns the bullets as an array instead of a string
        # with line breaks; join them so the list repr is not persisted.
        note = "\n".join(str(x).strip() for x in note_raw if str(x).strip())
    else:
        note = str(note_raw).strip()

    if note:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        memory.append_progress(user, lang, f"\n## {stamp} (session summary)\n{note}\n")

    vocab_added = 0
    expr_added = 0
    if is_expr:
        # Mode 7: consolidate idiomatic expressions in expressions.md, deduplicated
        # against the ones already learned.
        exprs = _norm_expressions(data.get("expressions"))
        if exprs:
            known = memory.existing_expression_keys(user, lang)
            fresh = []
            for e in exprs:
                key = memory.normalize_expression(e["expression"])
                if key and key not in known:
                    fresh.append(e)
                    known.add(key)
            if fresh:
                stamp = datetime.now().strftime("%Y-%m-%d")
                lines = "\n".join(
                    f"- **{e['expression']}**"
                    + (f": {e['meaning']}" if e["meaning"] else "")
                    + (f" ({e['register']})" if e["register"] else "")
                    + (f" _(e.g. {e['example']})_" if e["example"] else "")
                    for e in fresh
                )
                memory.append_expressions(user, lang, f"\n## {stamp}\n{lines}\n")
                expr_added = len(fresh)
    else:
        vocab = llm_parse._norm_vocab(data.get("vocab"))
        # Dedup: do not reintroduce terms already in vocab.md.
        if vocab:
            known = memory.existing_vocab_terms(user, lang)
            hint_keys = _stt_hint_keys(user)
            deduped = []
            dropped = 0
            for v in vocab:
                key = memory.normalize_vocab_term(v["term"])
                if not key or key in known:
                    continue
                if key.lower() in hint_keys:
                    # A proper name from the learner's life, not learned vocabulary.
                    dropped += 1
                    continue
                deduped.append(v)
                known.add(key)
            if dropped:
                logger.info("[stt-hints] dropped %d terms from the vocabulary", dropped)
            vocab = deduped
        if vocab:
            stamp = datetime.now().strftime("%Y-%m-%d")
            lines = "\n".join(
                f"- **{v['term']}**"
                + (f": {v['translation']}" if v["translation"] else "")
                + (f" _(e.g. {v['example']})_" if v["example"] else "")
                for v in vocab
            )
            tag = f" (book: {session['book_slug']})" if session.get("book_slug") else ""
            memory.append_vocab(user, lang, f"\n## {stamp}{tag}\n{lines}\n")
            vocab_added = len(vocab)

    # Spaced repetition: create new cards for the freshly consolidated vocabulary.
    # Must not break the session close if it fails.
    try:
        srs.sync_from_vocab(user, lang)
    except Exception:
        logger.exception("[srs] failed to sync srs.json from vocab.md")

    # Cross-cutting progress layer: update skill-tracker.md. Must not break the
    # session close if it fails.
    tracker_updated = False
    try:
        await _update_skill_tracker(session)
        tracker_updated = True
    except Exception:
        logger.exception("[skill-tracker] failed to update the tracker")

    # Mode 8: update the book. Must not break the close if it fails.
    book_updated = False
    if session.get("book_slug"):
        try:
            await _update_book(session)
            book_updated = True
        except Exception:
            logger.exception("[book] failed to update the book")

    # Mode 9 (lesson): the analyst pass updates the topic status. Must not break
    # the close if it fails. set_topic_status never moves back down the scale.
    topic_id = session.get("topic_id")
    if topic_id:
        try:
            status = str(data.get("topic_status") or "").strip().lower()
            if status in syllabus.STATES:
                syllabus.set_topic_status(user, lang, topic_id, status)
        except Exception:
            logger.exception("[syllabus] failed to update the topic status")

    # Report shown to the learner on the summary screen, besides what is persisted.
    missed = [str(m).strip() for m in (data.get("missed_opportunities") or []) if str(m).strip()][
        :4
    ]
    session_vocab = [
        {
            "term": v["term"],
            "translation": v.get("translation", ""),
            "example": v.get("example", ""),
        }
        for v in (vocab if not is_expr else [])
    ]

    return {
        "progress_updated": bool(note),
        "vocab_added": vocab_added,
        "expressions_added": expr_added,
        "tracker_updated": tracker_updated,
        "book_updated": book_updated,
        "summary": note,
        "session_vocab": session_vocab,
        "missed_opportunities": missed,
    }


async def _finalize_assessment(session: dict) -> dict:
    """Close the initial assessment: seeds CEFR + skill tracker + curriculum."""
    user, lang = session["user"], session["lang"]
    transcript = memory.read_session_day(user, lang, session.get("day"), session.get("id"))
    if not transcript or session.get("turns", 0) == 0:
        return {"assessment": None}
    instruction = (
        "You are a language assessor. From the transcript of an initial assessment, "
        "estimate the learner's level and profile. Answer ONLY with a valid JSON "
        "object, no ```:\n"
        "{\n"
        '  "cefr": "one of A1, A2, A2-B1, B1, B1-B2, B2, C1, C2",\n'
        '  "scores": { ' + ", ".join(f'"{k}": <0-100>' for k in config.SKILL_KEYS) + " },\n"
        f'  "strengths": ["strengths, in {_SUPPORT}"],\n'
        f'  "weaknesses": ["areas or mistakes to work on, in {_SUPPORT}"],\n'
        f'  "focus": "recommended focus to start with (one sentence, in {_SUPPORT})",\n'
        f'  "milestones": ["3-5 next goals, in {_SUPPORT}"],\n'
        f'  "summary": "2-4 sentences in {_SUPPORT}: where the learner is and where to start"\n'
        "}\n"
        f"The 8 dimensions (key: meaning):\n{_skill_dims_text()}\n\n"
        "IMPORTANT about `focus` and `milestones`: you also get the learner's PROFILE, "
        "which says WHAT the learner wants the language for. The plan must serve that, "
        "not a generic learner: if the profile talks about travel and family life, do "
        "not propose work vocabulary or business language. And if the profile says "
        "speaking makes the learner anxious or that the priority is to loosen up, the "
        "`focus` MUST include an explicit limit of corrections per turn (one), because "
        "that number is what the teacher obeys during the week: fluency comes before "
        "accuracy. `milestones` in the learner's own terrain, with the words of their life."
    )
    # The profile goes with the transcript: without it the analyst does not know
    # what the language is for and proposes a generic plan.
    profile = memory.read_user_profile(user, lang)
    payload = transcript[-8000:]
    if profile.strip():
        payload = f"## Learner profile\n{profile.strip()}\n\n## Transcript\n{payload}"
    data = await _analyst_json(
        instruction,
        payload,
        max_tokens=700,
        label="assessment",
        user=session["user"],
    )
    cefr = str(data.get("cefr") or memory.read_user_cefr(user, lang)).strip()
    base = cefr_baseline(cefr)
    scores = {}
    for k in config.SKILL_KEYS:
        try:
            scores[k] = max(0, min(100, int((data.get("scores") or {}).get(k, base))))
        except (ValueError, TypeError):
            scores[k] = base
    strengths = [str(s).strip() for s in (data.get("strengths") or []) if str(s).strip()]
    weaknesses = [str(s).strip() for s in (data.get("weaknesses") or []) if str(s).strip()][:6]
    milestones = [str(s).strip() for s in (data.get("milestones") or []) if str(s).strip()][:5]
    focus = str(data.get("focus", "")).strip()
    summary = str(data.get("summary", "")).strip()

    day = datetime.now().strftime("%Y-%m-%d")
    report = (
        f"# Initial assessment ({day})\n\n"
        f"**Estimated level (CEFR):** {cefr}\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Strengths\n" + "".join(f"- {s}\n" for s in strengths) + "\n"
        "## To work on\n" + "".join(f"- {s}\n" for s in weaknesses) + "\n"
        f"## Initial focus\n{focus}\n"
    )
    fname = memory.write_assessment(user, lang, report)
    memory.set_user_cefr(user, lang, cefr)
    memory.write_skill_tracker(
        user, lang, cefr, scores, weaknesses, [], history_note="Initial assessment."
    )
    memory.write_curriculum(
        user, lang, next_cefr(cefr) or cefr, focus or "(to be defined)", milestones, []
    )
    # The full result is returned, not just the file name: the closing screen has
    # to show the learner their level right after the assessment.
    return {
        "assessment": fname,
        "cefr": cefr,
        "assessment_summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "focus": focus,
    }


async def _finalize_levelup(session: dict) -> dict:
    """Close the level-up test: if passed, raise the CEFR in USER.md and the tracker."""
    user, lang = session["user"], session["lang"]
    transcript = memory.read_session_day(user, lang, session.get("day"), session.get("id"))
    cur_cefr = memory.read_user_cefr(user, lang)
    target = session.get("target_cefr") or next_cefr(cur_cefr) or cur_cefr
    if not transcript or session.get("turns", 0) == 0:
        return {"levelup": None, "passed": False}
    instruction = (
        f"You are a language examiner. The learner has taken a test to move up from "
        f"level {cur_cefr} to level {target}. From the transcript, decide whether they "
        "pass. Be demanding but fair. Answer ONLY with a valid JSON object, no ```:\n"
        f'{{ "passed": true|false, "reason": "2-3 sentences in {_SUPPORT} explaining why" }}'
    )
    data = await _analyst_json(
        instruction,
        transcript[-8000:],
        max_tokens=400,
        label="levelup",
        user=session["user"],
    )
    passed = bool(data.get("passed"))
    reason = str(data.get("reason", "")).strip()
    day = datetime.now().strftime("%Y-%m-%d")
    report = (
        f"# Level-up test {cur_cefr} → {target} ({day})\n\n"
        f"**Result:** {'PASSED' if passed else 'Not passed yet'}\n\n"
        f"{reason}\n"
    )
    fname = memory.write_level_test(user, lang, cur_cefr, target, report)
    if passed:
        memory.set_user_cefr(user, lang, target)
        tr = memory.read_skill_tracker(user, lang)
        memory.write_skill_tracker(
            user,
            lang,
            target,
            tr["scores"],
            tr["active_errors"],
            tr["resolved_errors"],
            history_note=f"Moved up from {cur_cefr} to {target}.",
        )
    return {"levelup": fname, "passed": passed, "to": target if passed else None}


# What the history screen shows for a finished session.
_NOTE_KEYS = (
    "summary",
    "session_vocab",
    "missed_opportunities",
    "cefr",
    "assessment_summary",
    "strengths",
    "weaknesses",
    "focus",
    "passed",
    "to",
    "analysis_error",
)


def save_session_notes(session: dict, result: dict) -> None:
    """Keep the useful part of the closing pass next to the session log."""
    if not session.get("id") or not session.get("turns"):
        return
    notes = {k: result[k] for k in _NOTE_KEYS if result.get(k) not in (None, "", [])}
    if not notes:
        return
    try:
        memory.write_session_notes(session["user"], session["lang"], session["id"], notes)
    except OSError:
        logger.exception("[notes] could not save the session notes")


async def finalize_session(session: dict) -> dict:
    """Closing pass by mode, then its notes are saved for the history. Used by
    /session/end and by the expired-session sweeper, so an orphan session also
    feeds progress and the tracker."""
    result = await _finalize_by_mode(session)
    save_session_notes(session, result)
    return result


async def _finalize_by_mode(session: dict) -> dict:
    mode, sub = session["mode"], session.get("sub_mode")
    if mode == 6 and sub == "assessment":
        return await _finalize_assessment(session)
    if mode == 6 and sub == "test":
        return await _finalize_levelup(session)
    if mode == 6 and sub == "weekly_review":
        return {"weekly_review": True}  # already persisted at the opening
    return await _post_session_pass(session)
