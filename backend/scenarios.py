"""Role-play scenario library (mode 2).

Scenarios live in backend/prompts/scenarios/<category>/<id>.md: parametrizable
teaching content versioned with the code, not personal memory. The learner's
personal context comes in at runtime through the memory block (USER.md) and is
not hardcoded here.

File format:
- Minimal YAML frontmatter: title, description, level (optional).
- Markdown sections at level "## ". Those ending in a language tag such as
  "(de)" or "(en)" are language specific (vocabulary, phrases, register); the
  rest are shared (context, the teacher's role, expected flow).
- Placeholders __USER_NAME__ and __TARGET_LANG__ are filled in prompt_builder.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config
from .memory import parse_frontmatter


class ScenarioNotFound(KeyError):
    pass


_ID_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")
_SECTION_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
# Language suffix of a section, e.g. "## Vocabulary (fr)". Derived from
# config.SUPPORTED_LANGS: if it were hardcoded, every new language would
# silently lose its specific sections.
_LANG_TAG_RE = re.compile(r"\((" + "|".join(config.SUPPORTED_LANGS) + r")\)\s*$")


def scenarios_root() -> Path:
    """Base library, versioned with the code."""
    return config.PROMPTS_ROOT / "scenarios"


def user_scenarios_root() -> Path:
    """Scenarios added by users, in the shared data folder.

    They live outside the repo on purpose: they are read from disk on every
    request, so adding one means dropping a file, with no deploy and no git.
    If an id matches one in the base library, this one wins.
    """
    return config.DATA_DIR / "_shared" / "scenarios"


def _roots() -> list[Path]:
    """User scenarios first: they override the base library for the same id."""
    return [user_scenarios_root(), scenarios_root()]


def _scenario_path(scenario_id: str) -> Path:
    if not _ID_RE.match(scenario_id or ""):
        raise ScenarioNotFound(scenario_id)
    for root in _roots():
        if not root.is_dir():
            continue
        path = (root / f"{scenario_id}.md").resolve()
        # Traversal guard per root: _ID_RE already restricts the id, but a
        # symlink pointing outside would still slip through without this.
        if path.is_file() and root.resolve() in path.parents:
            return path
    raise ScenarioNotFound(scenario_id)


def _split_body(text: str) -> str:
    """Return the body after the frontmatter (or the whole text if there is none)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _split_sections(body: str) -> list[tuple[str, str]]:
    matches = list(_SECTION_RE.finditer(body))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((m.group(1), body[m.end() : end].strip()))
    return out


def _sections_for_lang(sections: list[tuple[str, str]], lang: str) -> list[tuple[str, str]]:
    """Keep shared sections plus those of the active language (suffix removed)."""
    keep: list[tuple[str, str]] = []
    for title, content in sections:
        m = _LANG_TAG_RE.search(title)
        if m:
            if m.group(1) != lang:
                continue
            title = _LANG_TAG_RE.sub("", title).strip()
        keep.append((title, content))
    return keep


def _bullets(content: str) -> list[str]:
    return [ln.strip()[2:].strip() for ln in content.splitlines() if ln.strip().startswith("- ")]


def list_scenarios() -> list[dict]:
    """Available scenarios (metadata for the frontend picker)."""
    seen: dict[str, dict] = {}
    for root in _roots():
        if not root.is_dir():
            continue
        for cat_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for path in sorted(cat_dir.glob("*.md")):
                sid = f"{cat_dir.name}/{path.stem}"
                if sid in seen:  # user scenarios already won: the base must not override them
                    continue
                fm = parse_frontmatter(path.read_text(encoding="utf-8"))
                seen[sid] = {
                    "id": sid,
                    "category": cat_dir.name,
                    "title": str(fm.get("title", path.stem)),
                    "description": str(fm.get("description", "")),
                    "level": str(fm.get("level", "")),
                }
    return [seen[k] for k in sorted(seen)]


def build_block(scenario_id: str, lang: str) -> tuple[str, dict]:
    """Build the scenario's system prompt block plus info for the frontend.

    Returns (block_md, scenario_info). block_md keeps its placeholders unfilled
    (prompt_builder._fill fills them). scenario_info feeds the scenario card in
    the frontend (vocab and phrases as lists of strings).
    """
    path = _scenario_path(scenario_id)
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    sections = _sections_for_lang(_split_sections(_split_body(text)), lang)

    title = str(fm.get("title", path.stem))
    parts = [f"## Role-play scenario: {title}"]
    info: dict = {
        "id": scenario_id,
        "category": scenario_id.split("/", 1)[0],
        "title": title,
        "description": str(fm.get("description", "")),
        "level": str(fm.get("level", "")),
        "register": "",
        "vocab": [],
        "phrases": [],
    }
    for sec_title, content in sections:
        parts.append(f"### {sec_title}\n{content}")
        low = sec_title.lower()
        if low.startswith("vocabulary"):
            info["vocab"] = _bullets(content)
        elif low.startswith("phrases"):
            info["phrases"] = _bullets(content)
        elif low.startswith("register"):
            info["register"] = " ".join(content.split())
    return "\n\n".join(parts), info
