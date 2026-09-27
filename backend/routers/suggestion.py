"""Home screen: greeting + suggested lesson ("Today's lesson" card)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import suggestion
from ..sessions import validate_ids

router = APIRouter()


@router.get("/suggestion/{user}/{lang}")
def home(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return suggestion.build_home(user, lang)
