"""Read the session logs back as a history of sessions.

The logs are one markdown file per day (`sessions/YYYY-MM-DD.md`, written by
memory.append_turn), and several sessions can share a day. Each turn carries
its session id in an HTML comment; turns written before that existed are
grouped as one session per day.
"""

from __future__ import annotations

import re

from . import memory

_TURN_RE = re.compile(r"(?m)^## Turn (\d{2}:\d{2}:\d{2}) \((.*)\)\s*$")
_SESSION_RE = re.compile(r"<!-- session: ([0-9a-zA-Z_-]+) -->")
_MODE_RE = re.compile(r"^mode (\d+)(?: · (.*))?$")
_FIELD_RE = re.compile(
    r"^- \*\*(Learner|Teacher|Corrections|New vocabulary|Suggestion)\*\*:\s?(.*)$"
)
_CORRECTION_RE = re.compile(r"^`(.*)` -> `(.*)`(?: \((.*)\))?$")
_VOCAB_RE = re.compile(r"^\*\*(.+?)\*\*(?::\s*(.*))?$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,40}$")

# Placeholders written for turns the learner did not speak.
_NOT_SPOKEN = {"(teacher opening)", "(weekly review)"}
_LEGACY_PREFIX = "day-"


def valid_id(session_id: str) -> bool:
    return bool(_ID_RE.match(session_id or ""))


def _parse_turn(time: str, head: str, body: str) -> dict:
    turn: dict = {
        "time": time,
        "learner": "",
        "teacher": "",
        "corrections": [],
        "new_vocab": [],
        "suggestion": "",
    }
    mode_m = _MODE_RE.match(head.strip())
    turn["mode"] = int(mode_m.group(1)) if mode_m else None
    turn["label"] = (mode_m.group(2) or "") if mode_m else head.strip()
    field = None
    for raw in body.splitlines():
        line = raw.rstrip()
        m = _FIELD_RE.match(line)
        if m:
            field, value = m.group(1), m.group(2).strip()
            if field == "Learner":
                turn["learner"] = "" if value in _NOT_SPOKEN else value
            elif field == "Teacher":
                turn["teacher"] = value
            elif field == "Suggestion":
                turn["suggestion"] = value
            continue
        item = line.strip()
        if field in ("Corrections", "New vocabulary") and item.startswith("- "):
            item = item[2:].strip()
            if item == "(none)":
                continue
            if field == "Corrections" and (c := _CORRECTION_RE.match(item)):
                turn["corrections"].append(
                    {"original": c.group(1), "corrected": c.group(2), "note": c.group(3) or ""}
                )
            elif field == "New vocabulary" and (v := _VOCAB_RE.match(item)):
                turn["new_vocab"].append({"term": v.group(1), "translation": v.group(2) or ""})
        elif field in ("Learner", "Teacher") and item and not line.startswith("<!--"):
            # A reply that spans several lines continues the last field.
            key = "learner" if field == "Learner" else "teacher"
            turn[key] = (turn[key] + "\n" + item).strip()
    return turn


def _sessions_of_day(user: str, lang: str, day: str) -> dict[str, dict]:
    """{session_id: {id, day, turns: [...]}} for one day file, in file order."""
    text = memory.read_session_day(user, lang, day)
    sessions: dict[str, dict] = {}
    marks = list(_TURN_RE.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        sid_m = _SESSION_RE.search(body)
        sid = sid_m.group(1) if sid_m else f"{_LEGACY_PREFIX}{day}"
        turn = _parse_turn(m.group(1), m.group(2), body)
        entry = sessions.setdefault(sid, {"id": sid, "day": day, "turns": []})
        entry["turns"].append(turn)
    return sessions


def _days(user: str, lang: str) -> list[str]:
    folder = memory.user_lang_dir(user, lang) / "sessions"
    return sorted(
        (p.stem for p in folder.glob("*.md") if _DAY_RE.match(p.stem)),
        reverse=True,
    )


def _summary(user: str, lang: str, entry: dict) -> dict:
    first = entry["turns"][0]
    preview = next(
        (t["learner"] or t["teacher"] for t in entry["turns"] if t["learner"] or t["teacher"]),
        "",
    )
    return {
        "id": entry["id"],
        "day": entry["day"],
        "started": first["time"][:5],
        "mode": first["mode"],
        "label": first["label"],
        "turns": len(entry["turns"]),
        "preview": preview[:140],
        "has_notes": memory.read_session_notes(user, lang, entry["id"]) is not None,
    }


def list_sessions(user: str, lang: str) -> list[dict]:
    """Every session, newest first."""
    out: list[dict] = []
    for day in _days(user, lang):
        # The day file is chronological: its first-seen order is start order.
        day_sessions = list(_sessions_of_day(user, lang, day).values())[::-1]
        out.extend(_summary(user, lang, e) for e in day_sessions)
    return out


def read_session(user: str, lang: str, session_id: str) -> dict | None:
    """One session with all its turns and the notes of its closing pass."""
    if session_id.startswith(_LEGACY_PREFIX):
        days = [session_id[len(_LEGACY_PREFIX) :]]
        if not _DAY_RE.match(days[0]):
            return None
    else:
        days = _days(user, lang)
    for day in days:
        entry = _sessions_of_day(user, lang, day).get(session_id)
        if entry:
            first = entry["turns"][0]
            return {
                "id": session_id,
                "day": day,
                "started": first["time"][:5],
                "mode": first["mode"],
                "label": first["label"],
                "turns": [
                    {
                        k: t[k]
                        for k in (
                            "time",
                            "learner",
                            "teacher",
                            "corrections",
                            "new_vocab",
                            "suggestion",
                        )
                    }
                    for t in entry["turns"]
                ],
                "notes": memory.read_session_notes(user, lang, session_id),
            }
    return None
