"""Pure helpers for the CEFR spine (no I/O). A leaf module so both the routers
and post_session can use it without circular imports."""

from __future__ import annotations

from . import config

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
