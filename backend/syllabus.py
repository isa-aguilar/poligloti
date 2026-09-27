"""CEFR syllabus: curated seed per language plus per-learner state.

Seed: backend/prompts/syllabus/<lang>.md (versioned).
State: <DATA_DIR>/<user>/<lang>/syllabus.md (one line per topic with its status).
Statuses: pending (implicit) -> seen -> practiced -> mastered. They never go down.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from . import config

STATES = ("pending", "seen", "practiced", "mastered")

_LEVEL_RE = re.compile(r"^## +([A-C][12])\s*$")
_TOPIC_RE = re.compile(r"^### +([a-c][12]-\d{2}) +· +(.+)$")
_FIELD_RE = re.compile(r"^- +\*\*(\w[\w ]*)\*\*: *(.*)$")
_SUBITEM_RE = re.compile(r"^  +- +(.+)$")
_STATE_LINE_RE = re.compile(r"^- +([a-c][12]-\d{2}) +· +(\w+) +· +(\d{4}-\d{2}-\d{2})\s*$")

_FIELD_KEYS = {
    "Grammar": "grammar",
    "Goal": "goal",
    "Key points": "key_points",
    "Examples": "examples",
    "Suggested practice": "practice",
}
_LIST_FIELDS = ("key_points", "examples")


def _blank_topic(topic_id: str, title: str) -> dict:
    return {
        "id": topic_id,
        "title": title,
        "grammar": "",
        "goal": "",
        "key_points": [],
        "examples": [],
        "practice": "",
    }


@lru_cache(maxsize=8)
def load_syllabus(lang: str) -> dict[str, list[dict]]:
    """Parse the seed into {level: [topics in order]}. Tolerates missing fields."""
    path = config.PROMPTS_ROOT / "syllabus" / f"{lang}.md"
    if not path.is_file():
        return {}
    levels: dict[str, list[dict]] = {}
    level = None
    topic = None
    field = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LEVEL_RE.match(line)
        if m:
            level = m.group(1)
            levels.setdefault(level, [])
            topic = None
            continue
        m = _TOPIC_RE.match(line)
        if m and level:
            topic = _blank_topic(m.group(1), m.group(2).strip())
            levels[level].append(topic)
            field = None
            continue
        if topic is None:
            continue
        m = _FIELD_RE.match(line)
        if m:
            key = _FIELD_KEYS.get(m.group(1).strip())
            field = key
            if key and key not in _LIST_FIELDS:
                topic[key] = m.group(2).strip()
            continue
        m = _SUBITEM_RE.match(line)
        if m and field in _LIST_FIELDS:
            topic[field].append(m.group(1).strip())
    return levels


def topic_by_id(lang: str, topic_id: str) -> dict | None:
    for topics in load_syllabus(lang).values():
        for t in topics:
            if t["id"] == topic_id:
                return t
    return None


def _state_path(user: str, lang: str):
    return config.DATA_DIR / user / lang / "syllabus.md"


def read_user_syllabus(user: str, lang: str) -> dict[str, dict]:
    """{topic_id: {status, date}} from syllabus.md. Empty if it does not exist."""
    path = _state_path(user, lang)
    if not path.is_file():
        return {}
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _STATE_LINE_RE.match(line)
        if m:
            out[m.group(1)] = {"status": m.group(2), "date": m.group(3)}
    return out


def _write_state(user: str, lang: str, state: dict[str, dict]) -> None:
    path = _state_path(user, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"---\nupdated: {date.today().isoformat()}\n---", "", "# Syllabus", ""]
    for topic_id, info in sorted(state.items()):
        lines.append(f"- {topic_id} · {info['status']} · {info['date']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_topic_status(user: str, lang: str, topic_id: str, status: str) -> None:
    """Set a topic's status. Never moves backwards on the STATES scale."""
    if status not in STATES:
        return
    state = read_user_syllabus(user, lang)
    prev = state.get(topic_id, {}).get("status", "pending")
    if STATES.index(status) <= STATES.index(prev):
        return
    state[topic_id] = {"status": status, "date": date.today().isoformat()}
    _write_state(user, lang, state)


def _work_level(user: str, lang: str) -> str:
    from . import memory  # lazy import, avoids cycles

    cefr = (memory.read_user_cefr(user, lang) or "A1")[:2].upper()
    levels = list(load_syllabus(lang).keys())
    if not levels:
        return ""
    return cefr if cefr in levels else levels[-1]


def next_topic(user: str, lang: str) -> dict | None:
    """Next topic to work on: pending at the current level > seen > practiced,
    then the same order on the following levels."""
    data = load_syllabus(lang)
    if not data:
        return None
    state = read_user_syllabus(user, lang)
    levels = list(data.keys())
    level = _work_level(user, lang)
    idx = levels.index(level) if level in levels else 0
    for lv in levels[idx:]:
        topics = data[lv]
        for status in ("pending", "seen", "practiced"):
            found = next(
                (t for t in topics if state.get(t["id"], {}).get("status", "pending") == status),
                None,
            )
            if found:
                return found
    return None


def topic_session_count(user: str, lang: str, topic_id: str) -> int:
    """Cheap approximation: 0 if pending, 1 if seen, 2+ if practiced."""
    status = read_user_syllabus(user, lang).get(topic_id, {}).get("status", "pending")
    return {"pending": 0, "seen": 1, "practiced": 2, "mastered": 3}.get(status, 0)


def last_lesson_date(user: str, lang: str) -> str | None:
    state = read_user_syllabus(user, lang)
    dates = [v["date"] for v in state.values() if v.get("date")]
    return max(dates) if dates else None


def syllabus_overview(user: str, lang: str) -> dict:
    """Frontend payload: levels with topics + status + next topic."""
    state = read_user_syllabus(user, lang)
    levels = []
    for lv, topics in load_syllabus(lang).items():
        levels.append(
            {
                "level": lv,
                "topics": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "status": state.get(t["id"], {}).get("status", "pending"),
                        "date": state.get(t["id"], {}).get("date"),
                    }
                    for t in topics
                ],
            }
        )
    nxt = next_topic(user, lang)
    return {"levels": levels, "next": {"id": nxt["id"], "title": nxt["title"]} if nxt else None}
