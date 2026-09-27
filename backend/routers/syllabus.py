"""CEFR syllabus router."""

from fastapi import APIRouter, HTTPException

from .. import memory, syllabus
from ..sessions import validate_ids

router = APIRouter()


@router.get("/syllabus/{user}/{lang}")
def syllabus_overview(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    if not memory.read_user_profile(user, lang):
        raise HTTPException(404, f"unknown user: {user!r}")
    return syllabus.syllabus_overview(user, lang)
