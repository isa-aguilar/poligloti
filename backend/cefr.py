"""Pure helpers for the CEFR spine (no I/O). A leaf module so both the routers
and post_session can use it without circular imports."""

from __future__ import annotations

import re

from . import config

# Levels inside free text: "B1", "A2-B1", "B1+", "A2 (estimated)".
_CEFR_TOKEN = re.compile(r"(?<![A-Z0-9])([A-C][12])(?![0-9])")


def normalize_cefr(raw: object) -> str | None:
    """Canonical CEFR level ('B1' or a range like 'A2-B1'), or None if there is
    no clear level.

    The analyst model answers in free text, and its level ends up in a file name
    (level-tests/<from>-to-<to>-<date>.md). Whatever comes in, the result is one
    of the six levels or a range of two, never a path. Lenient on purpose so a
    stored 'B1+' still reads as 'B1'.
    """
    found = _CEFR_TOKEN.findall(str(raw or "").upper())
    levels = sorted(set(found), key=config.CEFR_LEVELS.index)
    if len(levels) == 1:
        return levels[0]
    if len(levels) == 2:
        return f"{levels[0]}-{levels[1]}"
    return None


def is_canonical_cefr(value: object) -> bool:
    """For writing: only values already in canonical form are accepted."""
    return isinstance(value, str) and normalize_cefr(value) == value


# Starting score (0-100) per CEFR level, used to seed trackers.
CEFR_BASE = {"A1": 20, "A2": 35, "B1": 50, "B2": 65, "C1": 80, "C2": 92}


def cefr_baseline(cefr: str) -> int:
    """Starting score derived from the CEFR level (the mean for a range like 'A2-B1')."""
    found = [v for k, v in CEFR_BASE.items() if k in (cefr or "").upper()]
    return round(sum(found) / len(found)) if found else 40


def next_cefr(cefr: str) -> str | None:
    present = [lvl for lvl in config.CEFR_LEVELS if lvl in (cefr or "").upper()]
    if not present:
        return None
    i = config.CEFR_LEVELS.index(present[-1])
    return config.CEFR_LEVELS[i + 1] if i + 1 < len(config.CEFR_LEVELS) else None


def levelup_eligible(scores: dict) -> bool:
    vals = [v for v in scores.values() if isinstance(v, int)]
    if not vals:
        return False
    return round(sum(vals) / len(vals)) >= config.LEVELUP_SCORE_THRESHOLD
