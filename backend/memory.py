"""Read and write the markdown memory: <DATA_DIR>/<user>/<lang>/...

No SQLite and no vector DB: plain markdown files. Almost every write is an
append, so the files stay auditable, hand-editable and easy to sync or back up.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config


def slugify(text: str, max_len: int = 40) -> str:
    """Filesystem-safe slug (readings, writing threads)."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-") or "untitled"


def user_lang_dir(user: str, lang: str) -> Path:
    d = config.DATA_DIR / user / lang
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions").mkdir(exist_ok=True)
    return d


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _tail(text: str, n: int) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def read_user_profile(user: str, lang: str) -> str:
    return _read(user_lang_dir(user, lang) / "USER.md")


def read_profile_root(user: str) -> str:
    """Read <DATA_DIR>/<user>/profile.md (shared by all languages)."""
    return _read(config.DATA_DIR / user / "profile.md")


def parse_frontmatter(text: str) -> dict:
    """Minimal parser: `key: value` plus inline lists `[a, b]`."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data: dict = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value
    return data


_VOCAB_TERM_RE = re.compile(r"\*\*(.+?)\*\*")

# Leading articles ignored when comparing terms ("die Bordkarte" == "Bordkarte").
# French "l'" has no space after it, so it is its own alternative.
_ARTICLE_RE = re.compile(
    r"^(?:(?:der|die|das|den|dem|des|ein|eine|einen|einem|the|a|an|le|la|les|un|une)\s+|l['’])",
    re.IGNORECASE,
)


def normalize_vocab_term(term: str) -> str:
    """Comparison key for a vocabulary term (no article, lowercase)."""
    return _ARTICLE_RE.sub("", (term or "").strip().lower())


def existing_vocab_terms(user: str, lang: str) -> set[str]:
    """Terms already present in vocab.md, normalized for comparison."""
    terms: set[str] = set()
    for line in read_vocab(user, lang).splitlines():
        for match in _VOCAB_TERM_RE.findall(line):
            key = normalize_vocab_term(match)
            if key:
                terms.add(key)
    return terms


def _last_vocab_terms(vocab_md: str, n: int) -> list[str]:
    """Last n unique terms of vocab.md (without the translation)."""
    seen: dict[str, None] = {}
    # Walk backwards to pick the most recent ones, deduplicating as we go.
    for line in reversed(vocab_md.splitlines()):
        for match in _VOCAB_TERM_RE.findall(line):
            term = match.strip()
            if term and term not in seen:
                seen[term] = None
                if len(seen) >= n:
                    break
        if len(seen) >= n:
            break
    # Return in natural order (most recent last).
    return list(reversed(list(seen.keys())))


def build_stt_prompt(user: str, lang: str) -> str:
    """Build the speech-to-text prompt in the target language.

    Combines proper names from profile.md (the `stt_hints` field, shared by all
    languages) with the latest vocab.md terms of the active language. It keeps
    the recognizer from replacing unusual names with likely words of the language.

    The prompt is in the target language because the recognizer treats it as
    text said earlier in the same recording.
    """
    fm = parse_frontmatter(read_profile_root(user))
    hints_raw = fm.get("stt_hints") or []
    if isinstance(hints_raw, str):
        hints_raw = [hints_raw]
    hints = [h for h in hints_raw if h]

    vocab_md = read_vocab(user, lang)
    vocab_terms = _last_vocab_terms(vocab_md, n=config.STT_PROMPT_VOCAB_TAIL)

    parts = []
    if hints:
        parts.append(", ".join(hints) + ".")
    if vocab_terms:
        parts.append(" ".join(vocab_terms) + ".")
    prompt = " ".join(parts)
    # Whisper-style models cap the prompt at 224 tokens. STT_PROMPT_MAX_CHARS is
    # a conservative proxy in characters. Cut at the last space so no word is split.
    if len(prompt) > config.STT_PROMPT_MAX_CHARS:
        prompt = prompt[: config.STT_PROMPT_MAX_CHARS].rsplit(" ", 1)[0]
    return prompt


def read_progress_tail(user: str, lang: str, n: int | None = None) -> str:
    n = config.PROGRESS_TAIL_LINES if n is None else n
    return _tail(_read(user_lang_dir(user, lang) / "progress.md"), n)


def read_vocab(user: str, lang: str) -> str:
    return _read(user_lang_dir(user, lang) / "vocab.md")


def read_vocab_tail(user: str, lang: str, n: int | None = None) -> str:
    """Tail of vocab.md for the system prompt. The full file grows without bound
    with daily use, and prefilling all of it on every turn hurts latency and
    invalidates the KV-cache warmup. Post-session dedup still uses read_vocab()."""
    n = config.VOCAB_TAIL_LINES if n is None else n
    return _tail(read_vocab(user, lang), n)


def read_curriculum_focus(user: str, lang: str) -> str:
    """Active curriculum focus. For now, the whole curriculum.md if it exists."""
    return _read(user_lang_dir(user, lang) / "curriculum.md")


# ---------------------------------------------------------------------------
# Mode 7: native expressions (idiomatic, no literal translation)
# ---------------------------------------------------------------------------
def read_expressions(user: str, lang: str) -> str:
    return _read(user_lang_dir(user, lang) / "expressions.md")


# ---------------------------------------------------------------------------
# Pronunciation per phoneme (minimal pairs)
# ---------------------------------------------------------------------------
def read_phonemes(user: str, lang: str) -> str:
    return _read(user_lang_dir(user, lang) / "phonemes.md")


def write_phonemes(user: str, lang: str, text: str) -> None:
    (user_lang_dir(user, lang) / "phonemes.md").write_text(text, encoding="utf-8")


def read_expressions_tail(user: str, lang: str, n: int | None = None) -> str:
    n = config.EXPRESSIONS_TAIL_LINES if n is None else n
    return _tail(read_expressions(user, lang), n)


def normalize_expression(expr: str) -> str:
    """Comparison key for an expression (lowercase, no punctuation or extra spaces)."""
    s = re.sub(r"\s+", " ", (expr or "").strip().lower())
    # Inverted marks included for a Spanish support language.
    return s.strip(" .,;:!?\u00a1\u00bf\"'\u201c\u201d\u2026")


def existing_expression_keys(user: str, lang: str) -> set[str]:
    """Expressions already present in expressions.md, normalized for comparison."""
    keys: set[str] = set()
    for line in read_expressions(user, lang).splitlines():
        for match in _VOCAB_TERM_RE.findall(line):
            key = normalize_expression(match)
            if key:
                keys.add(key)
    return keys


def count_expressions(user: str, lang: str) -> int:
    """Number of learned expressions (unique '**...**' entries in expressions.md)."""
    return len(existing_expression_keys(user, lang))


def append_expressions(user: str, lang: str, text: str) -> None:
    path = user_lang_dir(user, lang) / "expressions.md"
    header = "# Native expressions\n" if not path.exists() else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(header + text.rstrip() + "\n")


def build_memory_block(user: str, lang: str) -> str:
    """Context block injected into the system prompt on every turn."""
    profile = read_user_profile(user, lang) or "(USER.md not initialized)"
    progress = read_progress_tail(user, lang) or "No progress history yet."
    vocab = read_vocab_tail(user, lang) or "No vocabulary yet."
    focus = read_curriculum_focus(user, lang) or (
        "No weekly focus set. Follow the learner's lead naturally."
    )
    expressions = read_expressions_tail(user, lang)
    block = (
        "## Learner memory\n\n"
        f"### Profile\n{profile}\n\n"
        f"### Recent progress\n{progress}\n\n"
        f"### Vocabulary being tracked\n{vocab}\n\n"
    )
    if expressions.strip():
        block += (
            "### Expressions being tracked\n"
            "Idiomatic expressions the learner has already worked on. When they fit, "
            "use them naturally to reinforce them; do not explain them again unless "
            "the learner gets them wrong.\n"
            f"{expressions}\n\n"
        )
    # SRS: terms that are due or recently failed, so the teacher recycles them in
    # conversation. Lazy import (srs imports memory) and try/except: without
    # srs.json or with a broken fsrs install the block simply omits the section.
    try:
        from . import srs as _srs

        weak = _srs.weak_terms(user, lang)
    except Exception:
        weak = []
    if weak:
        block += (
            "### Vocabulary to reinforce (spaced repetition)\n"
            "Try to use these words naturally in the conversation when they fit; "
            "do not list or explain them unless the learner gets them wrong: "
            + ", ".join(weak)
            + "\n\n"
        )
    block += f"### This week's focus\n{focus}\n"
    # Syllabus topic in progress (seen/practiced): modes 1-5 reinforce it the
    # same way as the weekly focus. Lazy import + try/except: a syllabus failure
    # must not break the block.
    try:
        from . import syllabus as _syllabus

        state = _syllabus.read_user_syllabus(user, lang)
        in_progress = [
            (tid, info) for tid, info in state.items() if info["status"] in ("seen", "practiced")
        ]
        if in_progress:
            tid, info = max(in_progress, key=lambda x: x[1]["date"])
            topic = _syllabus.topic_by_id(lang, tid)
            if topic:
                block += (
                    "\n### Syllabus topic in progress\n"
                    f"{topic['title']} ({info['status']}): {topic['goal']}\n"
                )
    except Exception:
        pass
    return block


def _session_path(user: str, lang: str, day: str | None = None) -> Path:
    day = day or datetime.now().strftime("%Y-%m-%d")
    return user_lang_dir(user, lang) / "sessions" / f"{day}.md"


def append_turn(
    user: str,
    lang: str,
    mode: int,
    turn: dict,
    label: str | None = None,
    session_id: str | None = None,
) -> None:
    """Append one turn to the day's session file.

    `label` tags the turn context in its header (role-play scenario, active
    reading, writing action) so the post-session pass and a human reader can
    tell the modes apart. `session_id` goes in an HTML comment under the header:
    several sessions share the day file, and the history and the analyst need
    to tell them apart.
    """
    path = _session_path(user, lang)
    now = datetime.now()
    new_file = not path.exists()

    corrections = turn.get("corrections") or []
    if corrections:
        corr_lines = "\n".join(
            f"  - `{c['original']}` -> `{c['corrected']}`"
            + (f" ({c['note']})" if c.get("note") else "")
            for c in corrections
        )
    else:
        corr_lines = "  - (none)"

    vocab = turn.get("new_vocab") or []
    if vocab:
        vocab_lines = "\n".join(
            f"  - **{v['term']}**" + (f": {v['translation']}" if v.get("translation") else "")
            for v in vocab
        )
    else:
        vocab_lines = "  - (none)"

    head = f"mode {mode}" + (f" · {label}" if label else "")
    block_parts = []
    if new_file:
        block_parts.append(f"# Session {now.strftime('%Y-%m-%d')} ({user} / {lang})\n")
    marker = f"<!-- session: {session_id} -->\n" if session_id else ""
    block_parts.append(
        f"## Turn {now.strftime('%H:%M:%S')} ({head})\n"
        f"{marker}"
        f"- **Learner**: {turn.get('transcript', '').strip()}\n"
        f"- **Teacher**: {turn.get('reply', '').strip()}\n"
        f"- **Corrections**:\n{corr_lines}\n"
        f"- **New vocabulary**:\n{vocab_lines}\n"
        f"- **Suggestion**: {turn.get('suggested_followup', '').strip()}\n"
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block_parts) + "\n")


def read_session_day(
    user: str, lang: str, day: str | None = None, session_id: str | None = None
) -> str:
    """The day's session log. With `session_id`, only that session's turns
    (the whole day if none of them carries the id, as in logs written before
    turns were tagged)."""
    text = _read(_session_path(user, lang, day))
    if not session_id or not text:
        return text
    blocks = re.split(r"(?m)^(?=## Turn )", text)
    mine = [b for b in blocks if f"<!-- session: {session_id} -->" in b]
    return "".join(mine).strip() if mine else text


def session_notes_path(user: str, lang: str, session_id: str) -> Path:
    return user_lang_dir(user, lang) / "sessions" / "notes" / f"{session_id}.json"


def write_session_notes(user: str, lang: str, session_id: str, notes: dict) -> None:
    """What the end-of-session pass produced (summary, vocabulary, missed
    phrases, assessment...), kept per session for the history screen."""
    path = session_notes_path(user, lang, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")


def read_session_notes(user: str, lang: str, session_id: str) -> dict | None:
    path = session_notes_path(user, lang, session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Mode 3: readings
# ---------------------------------------------------------------------------
def write_reading(
    user: str, lang: str, slug: str, title: str, text: str, truncated: bool = False
) -> str:
    """Archive the working text in readings/YYYY-MM-DD-<slug>.md.

    Returns the created file name. If one with the same slug already exists
    today, adds a -2, -3... suffix instead of overwriting it.
    """
    d = user_lang_dir(user, lang) / "readings"
    d.mkdir(exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    base = f"{day}-{slug}"
    path = d / f"{base}.md"
    n = 2
    while path.exists():
        path = d / f"{base}-{n}.md"
        n += 1
    header = f"# Reading: {title or slug} ({day})\n"
    if truncated:
        header += f"\n> Text truncated to {config.READING_MAX_CHARS} characters.\n"
    path.write_text(f"{header}\n{text.rstrip()}\n", encoding="utf-8")
    return path.name


# ---------------------------------------------------------------------------
# Mode 5: writing (email and chat)
# ---------------------------------------------------------------------------
def writing_thread_path(user: str, lang: str, sub_mode: str, slug: str) -> Path:
    """Thread path: email/YYYY-MM-DD-<slug>.md or chat/YYYY-MM-DD.md."""
    sub_dir = "email" if sub_mode == "email" else "chat"
    d = user_lang_dir(user, lang) / "writing" / sub_dir
    d.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    name = f"{day}-{slug}.md" if sub_mode == "email" else f"{day}.md"
    return d / name


def append_writing(
    user: str, lang: str, sub_mode: str, slug: str, subject: str, block: str
) -> None:
    """Append one message to the thread (from the learner or the simulated colleague)."""
    path = writing_thread_path(user, lang, sub_mode, slug)
    if not path.exists():
        day = datetime.now().strftime("%Y-%m-%d")
        kind = "Email thread" if sub_mode == "email" else "Chat"
        title = f"# {kind}: {subject} ({day})" if subject else f"# {kind} ({day})"
        path.write_text(f"{title}\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n" + block.rstrip() + "\n")


def append_progress(user: str, lang: str, text: str) -> None:
    path = user_lang_dir(user, lang) / "progress.md"
    header = "# Progress\n" if not path.exists() else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(header + text.rstrip() + "\n")


def append_vocab(user: str, lang: str, text: str) -> None:
    path = user_lang_dir(user, lang) / "vocab.md"
    header = "# Vocabulary\n" if not path.exists() else ""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(header + text.rstrip() + "\n")


_BOOK_HEADER_RE = re.compile(r"^## .*\(book: (?P<slug>[a-z0-9-]+)\)\s*$")


def vocab_for_book(user: str, lang: str, slug: str) -> list[str]:
    """vocab.md entries born in sessions of that book (sections headed
    '## YYYY-MM-DD (book: <slug>)'). Used by the book detail view; vocab.md
    stays the single source of vocabulary (and of the SRS)."""
    out: list[str] = []
    capture = False
    for ln in read_vocab(user, lang).splitlines():
        s = ln.strip()
        if s.startswith("## "):
            m = _BOOK_HEADER_RE.match(s)
            capture = bool(m and m.group("slug") == slug)
            continue
        if capture and s.startswith("- "):
            out.append(s[2:].strip())
    return out


# ---------------------------------------------------------------------------
# Mode 6: progress system (skill-tracker, curriculum, assessment, weekly
# reviews, level tests). All markdown, auditable and hand-editable.
# ---------------------------------------------------------------------------
def _parse_bullets(text: str, heading: str) -> list[str]:
    """List items '- ...' under a '## heading' until the next '##'."""
    out: list[str] = []
    capture = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            capture = s[3:].strip().lower() == heading.lower()
            continue
        if capture and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def _section_text(text: str, heading: str) -> str:
    """Prose under a '## heading' until the next '##'."""
    out: list[str] = []
    capture = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            if capture:
                break
            capture = s[3:].strip().lower() == heading.lower()
            continue
        if capture:
            out.append(ln)
    return "\n".join(out).strip()


def read_skill_tracker(user: str, lang: str) -> dict:
    """skill-tracker.md -> cefr, 8 scores, active/resolved errors."""
    text = _read(user_lang_dir(user, lang) / "skill-tracker.md")
    fm = parse_frontmatter(text)
    scores: dict[str, int | None] = {}
    for k in config.SKILL_KEYS:
        raw = fm.get(f"score_{k}")
        try:
            scores[k] = int(raw) if raw else None
        except (ValueError, TypeError):
            scores[k] = None
    return {
        "exists": bool(text),
        "cefr": fm.get("cefr"),
        "updated": fm.get("updated"),
        "scores": scores,
        "active_errors": _parse_bullets(text, "Active errors"),
        "resolved_errors": _parse_bullets(text, "Resolved errors"),
    }


# Score line inside a history entry: "scores: grammar=34 active_vocab=75 ...".
# Without it the frontmatter (rewritten whole every session) would be the ONLY
# copy of the numbers and the evolution would be lost: nothing to draw a
# progress curve with.
_HIST_SCORES_RE = re.compile(r"(?m)^scores:\s*(.+)$")
_HIST_ENTRY_RE = re.compile(r"(?m)^###\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\s*$")
_HISTORY_HEADING = "## History"


def _fmt_hist_scores(scores: dict) -> str:
    parts = [f"{k}={scores[k]}" for k in config.SKILL_KEYS if scores.get(k) is not None]
    return "scores: " + " ".join(parts) if parts else ""


def write_skill_tracker(
    user: str,
    lang: str,
    cefr: str | None,
    scores: dict,
    active_errors: list[str],
    resolved_errors: list[str],
    history_note: str | None = None,
) -> None:
    """Rewrite skill-tracker.md (current state) and APPEND to its history.

    Two things ACCUMULATE instead of being overwritten, and they are what
    answers "have I improved?": the scores of each history entry and the list
    of resolved errors.
    """
    path = user_lang_dir(user, lang) / "skill-tracker.md"
    prev = _read(path)
    hist_prev = prev.split(_HISTORY_HEADING, 1)[1].strip() if _HISTORY_HEADING in prev else ""
    # Resolved errors are a cumulative achievement: the analyst only reports the
    # ones resolved IN THIS session, so overwriting the section would erase
    # everything achieved before. Merge them keeping first-seen order.
    prev_resolved = _parse_bullets(prev, "Resolved errors")
    merged_resolved = list(prev_resolved)
    seen = {e.strip().lower() for e in merged_resolved}
    for e in resolved_errors:
        if e.strip().lower() not in seen:
            merged_resolved.append(e)
            seen.add(e.strip().lower())
    # An error that is active again no longer counts as resolved.
    active_lower = {e.strip().lower() for e in active_errors}
    merged_resolved = [e for e in merged_resolved if e.strip().lower() not in active_lower]

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["---", f"cefr: {cefr or ''}", f"updated: {stamp}"]
    for k in config.SKILL_KEYS:
        v = scores.get(k)
        lines.append(f"score_{k}: {v if v is not None else ''}")
    lines += ["---", "", "## Active errors"]
    lines += [f"- {e}" for e in active_errors]
    lines += ["", "## Resolved errors"]
    lines += [f"- {e}" for e in merged_resolved]
    lines += ["", _HISTORY_HEADING]
    entry = [f"### {stamp}"]
    hist_scores = _fmt_hist_scores(scores)
    if hist_scores:
        entry.append(hist_scores)
    if history_note:
        entry.append(history_note.strip())
    lines.append("\n".join(entry) + "\n")
    if hist_prev:
        lines.append(hist_prev)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def read_skill_history(user: str, lang: str) -> list[dict]:
    """Score time series, oldest first.

    Only entries with a `scores:` line are returned. Older entries without one
    are skipped on purpose: their numbers do not exist and inventing them would
    distort the curve.
    """
    text = _read(user_lang_dir(user, lang) / "skill-tracker.md")
    if _HISTORY_HEADING not in text:
        return []
    body = text.split(_HISTORY_HEADING, 1)[1]
    marks = list(_HIST_ENTRY_RE.finditer(body))
    out: list[dict] = []
    for i, m in enumerate(marks):
        chunk = body[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(body)]
        sm = _HIST_SCORES_RE.search(chunk)
        if not sm:
            continue
        scores: dict[str, int] = {}
        for pair in sm.group(1).split():
            k, _, v = pair.partition("=")
            if k in config.SKILL_KEYS and v.isdigit():
                scores[k] = int(v)
        if not scores:
            continue
        note = _HIST_SCORES_RE.sub("", chunk).strip()
        out.append({"date": m.group(1), "scores": scores, "note": note})
    out.reverse()  # the file keeps the most recent entry on top
    return out


def read_curriculum(user: str, lang: str) -> dict:
    text = _read(user_lang_dir(user, lang) / "curriculum.md")
    fm = parse_frontmatter(text)
    return {
        "exists": bool(text),
        "target_cefr": fm.get("target_cefr"),
        "focus": _section_text(text, "Weekly focus"),
        "milestones": _parse_bullets(text, "Next milestones"),
        "topics": _parse_bullets(text, "Topics to cover"),
    }


def write_curriculum(
    user: str,
    lang: str,
    target_cefr: str | None,
    focus: str,
    milestones: list[str],
    topics: list[str],
) -> None:
    path = user_lang_dir(user, lang) / "curriculum.md"
    day = datetime.now().strftime("%Y-%m-%d")
    parts = ["---", f"target_cefr: {target_cefr or ''}", f"updated: {day}", "---", ""]
    parts += ["## Weekly focus", focus.strip() or "(no focus set)", ""]
    parts += ["## Topics to cover"] + [f"- {t}" for t in topics] + [""]
    parts += ["## Next milestones"] + [f"- {m}" for m in milestones]
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")


# Level assumed when none has been measured. It gives the engine something to
# work with; it must NOT be shown as if it were the learner's level.
DEFAULT_CEFR = "A2-B1"


def read_user_cefr(user: str, lang: str) -> str:
    """Level for internal use: always returns something to compute with."""
    return read_user_cefr_declared(user, lang) or DEFAULT_CEFR


def read_user_cefr_declared(user: str, lang: str) -> str | None:
    """REAL level declared in USER.md, or None if there is none.

    Used by the home screen: showing the internal default to a learner starting
    a new language would display a level nobody measured, contradicting the
    card that invites her to take the initial assessment.
    """
    fm = parse_frontmatter(read_user_profile(user, lang))
    raw = str(fm.get("cefr_estimate") or "").strip()
    return raw or None


def set_user_cefr(user: str, lang: str, cefr: str) -> None:
    """Update cefr_estimate in the USER.md frontmatter."""
    path = user_lang_dir(user, lang) / "USER.md"
    text = _read(path)
    if not text:
        return
    if re.search(r"(?m)^cefr_estimate:.*$", text):
        text = re.sub(r"(?m)^cefr_estimate:.*$", f"cefr_estimate: {cefr}", text)
    elif text.startswith("---"):
        text = text.replace("---", f"---\ncefr_estimate: {cefr}", 1)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def has_assessment(user: str, lang: str) -> bool:
    """Has the initial assessment ever been taken?

    Looks at the `assessment/` folder, NOT the skill-tracker. A tracker can
    exist without an assessment (a level set by hand), and using it as the
    signal left the learner with no way to take the assessment: the app
    believed it was already done.
    """
    d = user_lang_dir(user, lang) / "assessment"
    return d.is_dir() and any(d.glob("*.md"))


def write_assessment(user: str, lang: str, text: str) -> str:
    d = user_lang_dir(user, lang) / "assessment"
    d.mkdir(exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    path = d / f"initial-{day}.md"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path.name


def iso_week_label(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def has_weekly_review_this_week(user: str, lang: str) -> bool:
    return (user_lang_dir(user, lang) / "weekly-reviews" / f"{iso_week_label()}.md").is_file()


def write_weekly_review(user: str, lang: str, text: str) -> str:
    d = user_lang_dir(user, lang) / "weekly-reviews"
    d.mkdir(exist_ok=True)
    path = d / f"{iso_week_label()}.md"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path.name


def list_weekly_reviews(user: str, lang: str) -> list[dict]:
    d = user_lang_dir(user, lang) / "weekly-reviews"
    if not d.is_dir():
        return []
    return [{"week": p.stem, "text": _read(p)} for p in sorted(d.glob("*.md"), reverse=True)]


def write_level_test(user: str, lang: str, frm: str, to: str, text: str) -> str:
    d = user_lang_dir(user, lang) / "level-tests"
    d.mkdir(exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    path = d / f"{frm}-to-{to}-{day}.md"
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path.name


def last_session_date(user: str, lang: str):
    """Date of the last recorded session, from the YYYY-MM-DD.md file names."""
    d = user_lang_dir(user, lang) / "sessions"
    files = sorted(d.glob("*.md")) if d.is_dir() else []
    for p in reversed(files):
        try:
            return datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
    return None
