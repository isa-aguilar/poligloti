"""Spaced repetition (SRS) with FSRS over <DATA_DIR>/<user>/<lang>/srs.json.

Anki-style self-graded active recall: cards are born from the vocab.md that the
post-session pass consolidates, the learner reviews them in the frontend with a
1-4 rating (Again/Hard/Good/Easy) and py-fsrs schedules the next review.

Serialization: each card stores the py-fsrs `Card.to_dict()` dict under the
"fsrs" key (round-trips with `Card.from_dict`). The whole file is written
atomically (tmp + os.replace) so a crash mid-write cannot corrupt the review
history.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fsrs import Card, Rating, Scheduler

from . import memory

logger = logging.getLogger(__name__)

# Tunables from the environment.
SRS_DUE_LIMIT = int(os.getenv("SRS_DUE_LIMIT", "20"))
SRS_WEAK_LAPSE_DAYS = int(os.getenv("SRS_WEAK_LAPSE_DAYS", "7"))

# No fuzzing: deterministic intervals (more predictable and testable; Anki's
# anti-clumping jitter adds nothing with a few dozen cards).
_scheduler = Scheduler(enable_fuzzing=False)

# vocab.md line written by the post-session pass:
#   - **term**: translation _(e.g. example)_
_VOCAB_LINE_RE = re.compile(r"^\s*-\s+\*\*(?P<term>.+?)\*\*\s*(?::\s*(?P<rest>.*))?$")
_EXAMPLE_RE = re.compile(r"_\(e\.g\.\s*(?P<example>.+?)\)_\s*$")


def _now() -> datetime:
    return datetime.now(UTC)


def srs_path(user: str, lang: str) -> Path:
    return memory.user_lang_dir(user, lang) / "srs.json"


def load(user: str, lang: str) -> dict:
    """SRS state for (user, lang). {"cards": {}} if missing or corrupt."""
    path = srs_path(user, lang)
    if not path.is_file():
        return {"cards": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("[srs] %s unreadable, ignored", path)
        return {"cards": {}}
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
        return {"cards": {}}
    return data


def save(user: str, lang: str, data: dict) -> None:
    """Atomic write: tmp in the same directory + os.replace."""
    path = srs_path(user, lang)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _parse_vocab_entries(vocab_md: str) -> list[dict]:
    """{term, translation, example} entries from the '- **term**: ...' lines."""
    entries: list[dict] = []
    for line in vocab_md.splitlines():
        m = _VOCAB_LINE_RE.match(line)
        if not m:
            continue
        term = m.group("term").strip()
        rest = (m.group("rest") or "").strip()
        example = ""
        em = _EXAMPLE_RE.search(rest)
        if em:
            example = em.group("example").strip()
            rest = rest[: em.start()].strip()
        if term:
            entries.append({"term": term, "translation": rest, "example": example})
    return entries


def sync_from_vocab(user: str, lang: str) -> dict:
    """Create new cards for vocab.md terms not yet in srs.json.

    Returns {"added": n, "total": n}. Idempotent: the key is the normalized
    term (memory.normalize_vocab_term), so syncing again neither duplicates
    nor resets the FSRS state of existing cards.
    """
    data = load(user, lang)
    cards = data["cards"]
    added = 0
    for entry in _parse_vocab_entries(memory.read_vocab(user, lang)):
        key = memory.normalize_vocab_term(entry["term"])
        if not key or key in cards:
            continue
        cards[key] = {
            "term": entry["term"],
            "translation": entry["translation"],
            "example": entry["example"],
            "fsrs": Card().to_dict(),  # new card: due right away (due=now)
            "added": _now().isoformat(),
            "last_review": None,
            "lapses": 0,
            "last_lapse": None,
        }
        added += 1
    if added:
        save(user, lang, data)
    return {"added": added, "total": len(cards)}


def _due_dt(record: dict) -> datetime:
    return datetime.fromisoformat(record["fsrs"]["due"])


def due_payload(user: str, lang: str, limit: int | None = None) -> dict:
    """Due cards for the review screen, sorted by due date ascending."""
    limit = SRS_DUE_LIMIT if limit is None else limit
    cards = load(user, lang)["cards"]
    now = _now()
    due = sorted((rec for rec in cards.values() if _due_dt(rec) <= now), key=_due_dt)
    return {
        "due": [
            {
                "term": rec["term"],
                "translation": rec["translation"],
                "example": rec["example"],
                "due": rec["fsrs"]["due"],
            }
            for rec in due[:limit]
        ],
        "total_cards": len(cards),
        "due_count": len(due),
    }


def review(user: str, lang: str, term: str, rating: int) -> dict:
    """Apply a self-graded review (1=Again, 2=Hard, 3=Good, 4=Easy) and persist it.

    Raises KeyError if the term has no card.
    """
    data = load(user, lang)
    key = memory.normalize_vocab_term(term)
    record = data["cards"][key]  # KeyError -> 404 in the router
    card, _log = _scheduler.review_card(
        Card.from_dict(record["fsrs"]), Rating(rating), review_datetime=_now()
    )
    record["fsrs"] = card.to_dict()
    record["last_review"] = _now().isoformat()
    if rating == int(Rating.Again):
        record["lapses"] = int(record.get("lapses") or 0) + 1
        record["last_lapse"] = _now().isoformat()
    save(user, lang, data)
    return {"term": record["term"], "next_due": record["fsrs"]["due"]}


def weak_terms(user: str, lang: str, n: int = 8) -> list[str]:
    """Terms to reinforce in conversation: overdue ones (most overdue first)
    and recent misses (Again). Injected into the system prompt."""
    cards = load(user, lang)["cards"]
    if not cards:
        return []
    now = _now()
    lapse_cutoff = now - timedelta(days=SRS_WEAK_LAPSE_DAYS)
    overdue = sorted((rec for rec in cards.values() if _due_dt(rec) <= now), key=_due_dt)
    out: list[str] = [rec["term"] for rec in overdue]
    for rec in cards.values():
        raw = rec.get("last_lapse")
        if not raw or rec["term"] in out:
            continue
        try:
            if datetime.fromisoformat(raw) >= lapse_cutoff:
                out.append(rec["term"])
        except ValueError:
            continue
    return out[:n]
