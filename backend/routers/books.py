"""Book library (mode 8): /books/<user>/<lang>[/<slug>]."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import books, memory
from ..sessions import validate_ids

router = APIRouter()


class BookCreateBody(BaseModel):
    title: str


@router.get("/books/{user}/{lang}")
def books_list(user: str, lang: str) -> dict:
    validate_ids(user, lang)
    return {"books": books.list_books(user, lang)}


@router.post("/books/{user}/{lang}")
def books_create(user: str, lang: str, body: BookCreateBody) -> dict:
    validate_ids(user, lang)
    if not body.title.strip():
        raise HTTPException(400, "the book needs a title")
    # Same shape as books_detail (with 'vocab') so the frontend can treat the
    # answer as a BookDetail without missing fields. A new book has no vocab yet.
    return {**books.create_book(user, lang, body.title.strip()), "vocab": []}


@router.get("/books/{user}/{lang}/{slug}")
def books_detail(user: str, lang: str, slug: str) -> dict:
    validate_ids(user, lang)
    if not books.valid_slug(slug):
        raise HTTPException(400, f"invalid slug: {slug!r}")
    book = books.read_book(user, lang, slug)
    if book is None:
        raise HTTPException(404, f"book not found: {slug!r}")
    return {**book, "vocab": memory.vocab_for_book(user, lang, slug)}
