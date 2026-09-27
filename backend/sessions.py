"""Shared in-process session state (single worker).

It lives here (not in app.py) so teacher, post_session and the routers can
import it without cycles: sessions only depends on config and post_session.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time

from fastapi import HTTPException

from . import config
from .post_session import finalize_session

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9_-]+$")

# session_id -> session state.
SESSIONS: dict[str, dict] = {}


def validate_ids(user: str, lang: str) -> None:
    if not _SLUG.match(user or ""):
        raise HTTPException(400, f"Invalid user_id: {user!r}")
    if lang not in config.SUPPORTED_LANGS:
        raise HTTPException(400, f"Unsupported target_language: {lang!r}")


def purge_session_audio(session_id: str) -> None:
    """TTS audio is ephemeral: it is only played during the active session.
    Without this, WAV files pile up on disk without limit."""
    shutil.rmtree(config.AUDIO_ROOT / session_id, ignore_errors=True)


def sweep_stale_audio(max_age_h: float = 48.0) -> None:
    """Startup sweep: audio of orphan sessions (lost /session/end beacon,
    backend restarted mid-session)."""
    cutoff = time.time() - max_age_h * 3600
    removed = 0
    for entry in config.AUDIO_ROOT.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("audio sweep: removed %d orphan session directories", removed)


async def expire_stale_sessions_loop() -> None:
    """Sessions idle for more than SESSION_TTL_S (the /session/end beacon is lost
    when a mobile browser kills the PWA) are finalized like a normal close
    (their progress is persisted) and their memory and audio are freed."""
    while True:
        await asyncio.sleep(config.SESSION_SWEEP_INTERVAL_S)
        now = time.monotonic()
        stale = [
            sid
            for sid, s in SESSIONS.items()
            if now - s.get("last_activity", now) > config.SESSION_TTL_S
        ]
        for sid in stale:
            session = SESSIONS.pop(sid, None)
            if not session:
                continue
            logger.info(
                "session %s (%s/%s mode %s) expired without /session/end: finalizing",
                sid,
                session.get("user"),
                session.get("lang"),
                session.get("mode"),
            )
            try:
                await finalize_session(session)
            except Exception:
                logger.exception("failed to finalize expired session %s", sid)
            purge_session_audio(sid)
