"""Serialized graded stories (graded reader pattern, one chapter at a time).

Each story lives in <DATA_DIR>/<user>/<lang>/stories/<slug>.md: frontmatter
(title, level, chapters, created, updated) + one '## Chapter N' section per
chapter. Each chapter ends with an HTML comment '<!-- summary: ... -->' of 2-3
sentences: it gives the model context to write the next chapter without
prefilling the whole story again.

The frontend uses the chapter text as the `context` of a regular mode 3
(guided reading) session; this module does NOT touch the session flow.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from . import config, memory
from .post_session import _analyst_json

logger = logging.getLogger(__name__)

# Tunables from the environment.
STORY_WORDS = os.getenv("STORY_WORDS", "120-150")
STORY_MAX_TOKENS = int(os.getenv("STORY_MAX_TOKENS", "500"))
STORY_TEMPERATURE = float(os.getenv("STORY_TEMPERATURE", "0.7"))
STORY_WEAK_TERMS = int(os.getenv("STORY_WEAK_TERMS", "5"))

# Same alphabet as memory.slugify: path safety for routes with {slug}.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

_CHAPTER_RE = re.compile(r"(?m)^## Chapter (\d+)\s*$")
_SUMMARY_RE = re.compile(r"<!--\s*summary:\s*(.*?)\s*-->", re.DOTALL)


class StoryGenError(Exception):
    """The model did not return a usable chapter (invalid or empty JSON)."""


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def stories_dir(user: str, lang: str) -> Path:
    d = memory.user_lang_dir(user, lang) / "stories"
    d.mkdir(exist_ok=True)
    return d


def _story_path(user: str, lang: str, slug: str) -> Path:
    return stories_dir(user, lang) / f"{slug}.md"


def _weak_terms_safe(user: str, lang: str) -> list[str]:
    try:
        from . import srs

        return srs.weak_terms(user, lang, n=STORY_WEAK_TERMS)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Reading and writing the story file
# ---------------------------------------------------------------------------
def _parse_story(text: str) -> dict | None:
    """{"title", "level", "created", "updated", "chapters": [{n, text, summary}]}"""
    if not text:
        return None
    fm = memory.parse_frontmatter(text)
    body = text.split("---", 2)[2] if text.startswith("---") else text
    chapters: list[dict] = []
    matches = list(_CHAPTER_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section = body[m.end() : end]
        sm = _SUMMARY_RE.search(section)
        summary = sm.group(1).strip() if sm else ""
        chapter_text = _SUMMARY_RE.sub("", section).strip()
        chapters.append({"n": int(m.group(1)), "text": chapter_text, "summary": summary})
    chapters.sort(key=lambda c: c["n"])
    return {
        "title": str(fm.get("title") or ""),
        "level": str(fm.get("level") or ""),
        "created": str(fm.get("created") or ""),
        "updated": str(fm.get("updated") or ""),
        "chapters": chapters,
    }


def _write_story(path: Path, title: str, level: str, created: str, chapters: list[dict]) -> None:
    """Rewrite the whole file (atomic: tmp + os.replace)."""
    day = datetime.now().strftime("%Y-%m-%d")
    parts = [
        "---",
        f"title: {title}",
        f"level: {level}",
        f"chapters: {len(chapters)}",
        f"created: {created or day}",
        f"updated: {day}",
        "---",
    ]
    for ch in chapters:
        # The summary goes in a one-line HTML comment; neutralize its terminator.
        summary = re.sub(r"\s+", " ", ch.get("summary", "")).replace("-->", "->").strip()
        parts += ["", f"## Chapter {ch['n']}", "", ch["text"].strip()]
        if summary:
            parts += ["", f"<!-- summary: {summary} -->"]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def list_stories(user: str, lang: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted(stories_dir(user, lang).glob("*.md")):
        story = _parse_story(path.read_text(encoding="utf-8"))
        if not story:
            continue
        out.append(
            {
                "slug": path.stem,
                "title": story["title"] or path.stem,
                "level": story["level"],
                "chapters": len(story["chapters"]),
                "updated": story["updated"],
            }
        )
    out.sort(key=lambda s: (s["updated"], s["slug"]), reverse=True)
    return out


def read_story(user: str, lang: str, slug: str) -> dict | None:
    path = _story_path(user, lang, slug)
    if not path.is_file():
        return None
    return _parse_story(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Generation with the model
# ---------------------------------------------------------------------------
def _weak_terms_clause(terms: list[str]) -> str:
    if not terms:
        return ""
    return (
        "Naturally weave in 3-5 of these words the learner is reviewing "
        f"(without highlighting or explaining them): {', '.join(terms)}. "
    )


def _lang_name(lang: str) -> str:
    return config.LANG_NAMES.get(lang, lang)


async def create_story(user: str, lang: str, topic: str | None = None) -> dict:
    """Generate chapter 1 and create stories/<slug>.md. Returns
    {slug, title, level, chapter, text}."""
    level = memory.read_user_cefr(user, lang)
    weak = _weak_terms_safe(user, lang)
    instruction = (
        "You write serialized stories for language learners. "
        f"Write chapter 1 of an original story in {_lang_name(lang)}, "
        f"adapted to CEFR level {level}: {STORY_WORDS} words, with sentences and "
        "vocabulary suited to that level, and end the chapter with a small hook "
        "that makes the reader want to continue. "
        + _weak_terms_clause(weak)
        + "Reply ONLY with a valid JSON object, no extra text and no ```:\n"
        "{\n"
        '  "title": "short story title, in the language of the story",\n'
        '  "chapter": "the chapter text, prose only",\n'
        '  "summary": "summary of the chapter in 2-3 sentences, in the language of the story"\n'
        "}"
    )
    payload = (
        f"Topic suggested by the learner: {topic.strip()}"
        if topic and topic.strip()
        else "Free topic: pick an engaging everyday or work topic yourself."
    )
    data = await _analyst_json(
        instruction,
        payload,
        max_tokens=STORY_MAX_TOKENS,
        label="story-ch1",
        temperature=STORY_TEMPERATURE,
        user=user,
    )
    text = str(data.get("chapter", "")).strip()
    if not text:
        raise StoryGenError("the model returned no chapter")
    title = str(data.get("title", "")).strip() or (topic or "").strip() or "Story"
    summary = str(data.get("summary", "")).strip()

    slug = memory.slugify(title)
    path = _story_path(user, lang, slug)
    n = 2
    while path.exists():
        path = _story_path(user, lang, f"{slug}-{n}")
        n += 1
    _write_story(
        path,
        title,
        level,
        created="",
        chapters=[{"n": 1, "text": text, "summary": summary}],
    )
    return {"slug": path.stem, "title": title, "level": level, "chapter": 1, "text": text}


async def next_chapter(user: str, lang: str, slug: str) -> dict:
    """Generate chapter N+1 from the title, level and previous summaries and
    append it to the file. Raises FileNotFoundError if the story does not exist."""
    path = _story_path(user, lang, slug)
    story = read_story(user, lang, slug)
    if story is None:
        raise FileNotFoundError(slug)
    n = len(story["chapters"]) + 1
    level = story["level"] or memory.read_user_cefr(user, lang)
    weak = _weak_terms_safe(user, lang)
    instruction = (
        "You write serialized stories for language learners. "
        f"Continue the story in {_lang_name(lang)} with chapter {n}, consistent "
        f"with what has happened so far, adapted to CEFR level {level}: {STORY_WORDS} "
        "words and a small final hook that makes the reader want to continue. "
        + _weak_terms_clause(weak)
        + "Reply ONLY with a valid JSON object, no extra text and no ```:\n"
        "{\n"
        '  "chapter": "the chapter text, prose only",\n'
        '  "summary": "summary of the chapter in 2-3 sentences, in the language of the story"\n'
        "}"
    )
    summaries = "\n".join(
        f"- Chapter {ch['n']}: {ch['summary'] or '(no summary)'}" for ch in story["chapters"]
    )
    payload = (
        f"Title: {story['title']}\n"
        f"Level: {level}\n"
        f"Summary of the previous chapters:\n{summaries}\n\n"
        f"Write chapter {n}."
    )
    data = await _analyst_json(
        instruction,
        payload,
        max_tokens=STORY_MAX_TOKENS,
        label="story-next",
        temperature=STORY_TEMPERATURE,
        user=user,
    )
    text = str(data.get("chapter", "")).strip()
    if not text:
        raise StoryGenError("the model returned no chapter")
    summary = str(data.get("summary", "")).strip()
    chapters = story["chapters"] + [{"n": n, "text": text, "summary": summary}]
    _write_story(path, story["title"], level, story["created"], chapters)
    return {"slug": slug, "chapter": n, "text": text}
