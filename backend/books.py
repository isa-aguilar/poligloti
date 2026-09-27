"""Book entity (mode 8): <DATA_DIR>/<user>/<lang>/books/<slug>.md.

Frontmatter (title, created, updated, page, status, sessions) + a
'## Thread summary' section (rewritten by the analyst pass at the end of each
session) + '## History' (append, most recent first). The book's vocabulary does
NOT live here: it is in vocab.md tagged '(book: <slug>)' (single source for the
SRS). Mirrors stories.py.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import memory

# Same alphabet as memory.slugify: path safety for routes with {slug}.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def books_dir(user: str, lang: str) -> Path:
    d = memory.user_lang_dir(user, lang) / "books"
    d.mkdir(exist_ok=True)
    return d


def _book_path(user: str, lang: str, slug: str) -> Path:
    return books_dir(user, lang) / f"{slug}.md"


def _parse_book(slug: str, text: str) -> dict | None:
    if not text:
        return None
    fm = memory.parse_frontmatter(text)
    try:
        page = int(fm.get("page") or 0)
    except (ValueError, TypeError):
        page = 0
    try:
        sessions = int(fm.get("sessions") or 0)
    except (ValueError, TypeError):
        sessions = 0
    return {
        "slug": slug,
        "title": str(fm.get("title") or slug),
        "created": str(fm.get("created") or ""),
        "updated": str(fm.get("updated") or ""),
        "page": page,
        "status": str(fm.get("status") or "active"),
        "sessions": sessions,
        "summary": memory._section_text(text, "Thread summary"),
        "history": memory._parse_bullets(text, "History"),
    }


def read_book(user: str, lang: str, slug: str) -> dict | None:
    path = _book_path(user, lang, slug)
    if not path.is_file():
        return None
    return _parse_book(slug, path.read_text(encoding="utf-8"))


def list_books(user: str, lang: str) -> list[dict]:
    """Books sorted by 'updated' descending (most recent first)."""
    out: list[dict] = []
    for p in books_dir(user, lang).glob("*.md"):
        book = _parse_book(p.stem, p.read_text(encoding="utf-8"))
        if book:
            out.append(
                {k: book[k] for k in ("slug", "title", "page", "status", "sessions", "updated")}
            )
    return sorted(out, key=lambda b: b["updated"], reverse=True)


def _write_book(user: str, lang: str, book: dict) -> None:
    day = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "---",
        f"title: {book['title']}",
        f"created: {book['created'] or day}",
        f"updated: {day}",
        f"page: {book['page']}",
        f"status: {book['status']}",
        f"sessions: {book['sessions']}",
        "---",
        "",
        "## Thread summary",
        book["summary"].strip() or "(no summary yet: first session pending)",
        "",
        "## History",
    ]
    lines += [f"- {h}" for h in book["history"]]
    _book_path(user, lang, book["slug"]).write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8"
    )


def create_book(user: str, lang: str, title: str) -> dict:
    """Create the book with a slug derived from the title (-2, -3... suffix on collision)."""
    base = memory.slugify(title)
    slug, n = base, 2
    while _book_path(user, lang, slug).exists():
        slug = f"{base}-{n}"
        n += 1
    book = {
        "slug": slug,
        "title": (title or "").strip() or slug,
        "created": "",
        "updated": "",
        "page": 0,
        "status": "active",
        "sessions": 0,
        "summary": "",
        "history": [],
    }
    _write_book(user, lang, book)
    return read_book(user, lang, slug) or book


def update_book(
    user: str, lang: str, slug: str, *, page: int, summary: str, history_line: str
) -> None:
    """End of a book session: set the page, REPLACE the thread summary (it is
    cumulative: the analyst pass already writes it including what came before)
    and add a history line (most recent first)."""
    book = read_book(user, lang, slug)
    if book is None:
        return
    day = datetime.now().strftime("%Y-%m-%d")
    book["page"] = int(page)
    if summary.strip():
        book["summary"] = summary.strip()
    book["sessions"] += 1
    book["history"] = [f"{day} · {history_line}"] + book["history"]
    _write_book(user, lang, book)
