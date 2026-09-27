"""Graded serial stories: /stories/<user>/<lang>[/<slug>[/next]].

The frontend uses the chapter text as the `context` of a regular mode 3
(guided reading) session; here the story is only generated and persisted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import stories
from ..sessions import validate_ids

router = APIRouter()


class StoryCreateBody(BaseModel):
    topic: str | None = None


def _check_slug(slug: str) -> None:
    if not stories.valid_slug(slug):
        raise HTTPException(400, f"invalid slug: {slug!r}")


@router.get("/stories/{user}/{lang}")
def stories_list(user: str, lang: str) -> list[dict]:
    validate_ids(user, lang)
    return stories.list_stories(user, lang)


@router.post("/stories/{user}/{lang}")
async def stories_create(user: str, lang: str, body: StoryCreateBody | None = None) -> dict:
    validate_ids(user, lang)
    topic = body.topic if body else None
    try:
        return await stories.create_story(user, lang, topic)
    except stories.StoryGenError:
        raise HTTPException(502, "the chat model did not return a valid chapter") from None


@router.get("/stories/{user}/{lang}/{slug}")
def stories_detail(user: str, lang: str, slug: str) -> dict:
    validate_ids(user, lang)
    _check_slug(slug)
    story = stories.read_story(user, lang, slug)
    if story is None:
        raise HTTPException(404, f"story not found: {slug!r}") from None
    return {
        "slug": slug,
        "title": story["title"],
        "level": story["level"],
        "chapters": [{"n": ch["n"], "text": ch["text"]} for ch in story["chapters"]],
    }


@router.post("/stories/{user}/{lang}/{slug}/next")
async def stories_next(user: str, lang: str, slug: str) -> dict:
    validate_ids(user, lang)
    _check_slug(slug)
    try:
        return await stories.next_chapter(user, lang, slug)
    except FileNotFoundError:
        raise HTTPException(404, f"story not found: {slug!r}") from None
    except stories.StoryGenError:
        raise HTTPException(502, "the chat model did not return a valid chapter") from None
