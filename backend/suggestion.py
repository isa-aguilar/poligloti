"""Lesson suggestion for the home screen ("Today's lesson" card).

Rule-based, no model call: computed instantly from the progress signals already
on disk (skill-tracker, curriculum, SRS, session files, vocab.md). The
suggestion is only a hint; the learner can pick any mode anyway.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import memory, prompt_builder, srs, syllabus, teacher

# Weakest tracker skill -> suggested mode. A common-sense mapping, meant to be
# tuned with use.
_SKILL_TO_MODE = {
    "pronunciation": 4,  # read aloud
    "reading": 3,  # guided reading
    "grammar": 5,  # writing
    "writing": 5,  # writing
    "technical_vocab": 2,  # role-play (work)
    "listening": 2,  # role-play
    "active_vocab": 1,  # free talk
    "speaking": 1,  # free talk
}

_NO_FOCUS = "(no focus set)"  # placeholder written by memory.write_curriculum
_VOCAB_LINE = re.compile(r"^\s*-\s+\*\*")


def _streak(user: str, lang: str) -> int:
    """Consecutive days with a session, counting back from today (or from
    yesterday if there is no session yet today). No sessions: 0."""
    days: set[date] = set()
    for p in (memory.user_lang_dir(user, lang) / "sessions").glob("*.md"):
        try:
            days.add(date.fromisoformat(p.stem))
        except ValueError:
            continue
    if not days:
        return 0
    today = datetime.now().date()
    if today in days:
        cursor = today
    elif (today - timedelta(days=1)) in days:
        cursor = today - timedelta(days=1)
    else:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _vocab_count(user: str, lang: str) -> int:
    return sum(1 for ln in memory.read_vocab(user, lang).splitlines() if _VOCAB_LINE.match(ln))


def build_greeting(user: str, lang: str) -> dict:
    tr = memory.read_skill_tracker(user, lang)
    return {
        "name": prompt_builder.user_display_name(user),
        # None if nobody has measured the level: the card omits it instead of
        # showing an invented level.
        "cefr": tr.get("cefr") or memory.read_user_cefr_declared(user, lang),
        "streak": _streak(user, lang),
        "vocab_count": _vocab_count(user, lang),
    }


def _sug(
    kind: str, *, mode=None, route=None, count=None, focus=None, skill=None, topic_id=None
) -> dict:
    return {
        "kind": kind,
        "mode": mode,
        "route": route,
        "count": count,
        "focus": focus,
        "skill": skill,
        "topic_id": topic_id,
    }


def build_suggestion(user: str, lang: str) -> dict:
    tr = memory.read_skill_tracker(user, lang)
    # 1) No initial assessment: until it is done there is no real progress to
    # measure. The signal is the assessment/ folder, not the tracker: a tracker
    # set by hand made the app believe the learner was assessed and hid the
    # card forever.
    if not memory.has_assessment(user, lang):
        return _sug("assessment", mode=6)
    # 2) Weekly review due (mode 1 opens with the review).
    if teacher.weekly_review_due(user, lang):
        return _sug("review", mode=1)
    # 3) SRS words due -> Review screen.
    due_count = srs.due_payload(user, lang).get("due_count", 0)
    if due_count > 0:
        return _sug("srs", route="/review", count=due_count)
    # 3.5) Syllabus lesson (2-day cooldown to keep variety: focus/skill
    # suggestions still show up on the days in between).
    topic = syllabus.next_topic(user, lang)
    if topic is not None:
        last = syllabus.last_lesson_date(user, lang)
        if last is None or (date.today() - date.fromisoformat(last)).days >= 2:
            return _sug("lesson", mode=9, focus=topic["title"], topic_id=topic["id"])
    # 4) Curriculum weekly focus -> conversation that brings it up.
    focus = (memory.read_curriculum(user, lang).get("focus") or "").strip()
    if focus and focus != _NO_FOCUS:
        return _sug("focus", mode=1, focus=focus)
    # 5) Weakest tracker skill -> mapped mode.
    scores = {k: v for k, v in (tr.get("scores") or {}).items() if isinstance(v, int)}
    if scores:
        weak = min(scores, key=lambda k: scores[k])
        return _sug("skill", mode=_SKILL_TO_MODE.get(weak, 1), skill=weak)
    # 6) Fallback: just chat for a while.
    return _sug("free", mode=1)


def build_home(user: str, lang: str) -> dict:
    return {"greeting": build_greeting(user, lang), "suggestion": build_suggestion(user, lang)}
