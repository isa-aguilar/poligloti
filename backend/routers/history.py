"""History of past sessions: GET /sessions/{user}/{lang} and one session in detail."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import session_log
from ..sessions import validate_ids

router = APIRouter()


@router.get("/sessions/{user}/{lang}")
def sessions_list(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return {"sessions": session_log.list_sessions(user, lang)}


@router.get("/sessions/{user}/{lang}/{session_id}")
def session_detail(user: str, lang: str, session_id: str) -> dict:
    validate_ids(user, lang)
    if not session_log.valid_id(session_id):
        raise HTTPException(400, f"invalid session id: {session_id!r}")
    session = session_log.read_session(user, lang, session_id)
    if session is None:
        raise HTTPException(404, f"session not found: {session_id!r}")
    return session
