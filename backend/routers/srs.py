"""Spaced repetition (SRS): /srs/<user>/<lang>/{due,review,sync}.

The frontend review screen asks for the due cards, shows the term (active
recall) and sends the 1-4 self-grade; FSRS decides the next review.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import srs
from ..sessions import validate_ids

router = APIRouter()


class SRSReviewBody(BaseModel):
    term: str
    # 1=Again, 2=Hard, 3=Good, 4=Easy (Anki/FSRS scale).
    rating: int = Field(ge=1, le=4)


@router.get("/srs/{user}/{lang}/due")
def srs_due(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return srs.due_payload(user, lang)


@router.post("/srs/{user}/{lang}/review")
def srs_review(user: str, lang: str, body: SRSReviewBody) -> dict:
    validate_ids(user, lang)
    try:
        return srs.review(user, lang, body.term, body.rating)
    except KeyError:
        raise HTTPException(404, f"no SRS card for the term: {body.term!r}") from None


@router.post("/srs/{user}/{lang}/sync")
def srs_sync(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return srs.sync_from_vocab(user, lang)
