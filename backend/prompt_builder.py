"""Resolve and compose the system prompt: shared + mode + memory, with tokens filled in."""

from __future__ import annotations

from . import config, memory

MODE_FILES = {
    1: "mode-1-free-talk.md",
    2: "mode-2-roleplay.md",
    3: "mode-3-guided-reading.md",
    4: "mode-4-read-aloud.md",
    5: "mode-5-writing.md",
    7: "mode-7-expressions.md",
    8: "mode-8-book.md",
    9: "mode-9-lesson.md",
}


def user_display_name(user: str) -> str:
    """Display name from `name:` in the user's profile.md, else the capitalized id."""
    try:
        fm = memory.parse_frontmatter(memory.read_profile_root(user))
    except Exception:
        fm = {}
    name = str(fm.get("name") or "").strip()
    return name or user.capitalize()


def _fill(text: str, user: str, lang: str) -> str:
    return (
        text.replace("__TARGET_LANG__", config.LANG_NAMES.get(lang, lang))
        .replace("__SUPPORT_LANG__", config.UI_LANG_NAMES.get(config.SUPPORT_LANG, "English"))
        .replace("__USER_NAME__", user_display_name(user))
        .replace("__MAX_CORRECTIONS__", str(config.MAX_CORRECTIONS))
    )


def build_system_prompt(
    user: str,
    lang: str,
    mode: int,
    memory_block: str,
    extra_block: str | None = None,
) -> str:
    """shared + mode + (the mode's extra block: scenario, text, context) + memory."""
    shared = (config.PROMPTS_ROOT / "shared.md").read_text(encoding="utf-8")
    mode_file = config.PROMPTS_ROOT / lang / MODE_FILES.get(mode, MODE_FILES[1])
    mode_text = mode_file.read_text(encoding="utf-8")
    parts = [_fill(shared, user, lang), _fill(mode_text, user, lang)]
    if extra_block:
        parts.append(_fill(extra_block, user, lang))
    parts.append(memory_block)
    return "\n\n---\n\n".join(p.strip() for p in parts)


MODE6_FILES = {
    "assessment": "initial-assessment.md",
    "weekly_review": "weekly-review.md",
    "test": "level-up-test.md",
}


def build_mode6_prompt(
    user: str, lang: str, sub_mode: str, memory_block: str, extra_block: str | None = None
) -> str:
    """Mode 6 system prompt (assessment / weekly review / test): shared + sub-prompt + memory."""
    shared = (config.PROMPTS_ROOT / "shared.md").read_text(encoding="utf-8")
    fname = MODE6_FILES.get(sub_mode, MODE6_FILES["assessment"])
    mode_text = (config.PROMPTS_ROOT / lang / "mode-6-assessment" / fname).read_text(
        encoding="utf-8"
    )
    parts = [_fill(shared, user, lang), _fill(mode_text, user, lang)]
    if extra_block:
        parts.append(_fill(extra_block, user, lang))
    parts.append(memory_block)
    return "\n\n---\n\n".join(p.strip() for p in parts)


def build_colleague_prompt(user: str, lang: str, sub_mode: str, subject: str) -> str:
    """System prompt of the simulated mode 5 colleague (its own persona, not the teacher)."""
    fname = f"mode-5-colleague-{sub_mode}.md"
    text = (config.PROMPTS_ROOT / lang / fname).read_text(encoding="utf-8")
    return _fill(text, user, lang).replace("__SUBJECT__", subject or "(no subject)")
