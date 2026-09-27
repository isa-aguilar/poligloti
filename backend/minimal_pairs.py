"""Minimal pairs: phoneme-level pronunciation practice without a phonetic model.

Curated seed in backend/prompts/minimal-pairs/<lang>.md (contrast + tip +
pairs). The learner reads a pair aloud; speech-to-text WITHOUT a prompt
transcribes it and the verdict says whether the distinction was heard. A tally
per contrast lives in <DATA_DIR>/<user>/<lang>/phonemes.md (section
'Contrasts (minimal pairs)').
"""

from __future__ import annotations

import random
import re
from datetime import datetime

from . import config, memory

_GROUP_RE = re.compile(r"^## (?P<contrast>\S+) · (?P<desc>.+)$")
_PAIR_RE = re.compile(r"^- (?P<w1>[^/]+) / (?P<w2>[^—]+) — (?P<gloss>.+)$")
_TALLY_RE = re.compile(
    r"^- (?P<contrast>\S+) \((?P<pair>[^)]+)\): (?P<n>\d+) attempts? · "
    r"(?P<ok>\d+) distinguished · last (?P<day>\S+)$"
)

_SECTION = "## Contrasts (minimal pairs)"


def load_pairs(lang: str) -> list[dict]:
    """[{contrast, desc, tip, pairs: [{words: [w1, w2], gloss}]}] from the seed."""
    path = config.PROMPTS_ROOT / "minimal-pairs" / f"{lang}.md"
    if not path.is_file():
        return []
    groups: list[dict] = []
    cur: dict | None = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        m = _GROUP_RE.match(s)
        if m:
            cur = {"contrast": m.group("contrast"), "desc": m.group("desc"), "tip": "", "pairs": []}
            groups.append(cur)
            continue
        if cur is None:
            continue
        if s.startswith("tip:"):
            cur["tip"] = s[4:].strip()
            continue
        m = _PAIR_RE.match(s)
        if m:
            cur["pairs"].append(
                {
                    "words": [m.group("w1").strip(), m.group("w2").strip()],
                    "gloss": m.group("gloss").strip(),
                }
            )
    return [g for g in groups if g["pairs"]]


def _failed_contrasts(user: str, lang: str) -> list[str]:
    """Contrasts with more misses than hits in phonemes.md (worst first)."""
    text = memory.read_phonemes(user, lang)
    scored: list[tuple[int, str]] = []
    for ln in text.splitlines():
        m = _TALLY_RE.match(ln.strip())
        if m:
            fails = int(m.group("n")) - int(m.group("ok"))
            if fails > int(m.group("ok")):
                scored.append((fails, m.group("contrast")))
    return [c for _, c in sorted(scored, reverse=True)]


def pick_pairs(user: str, lang: str, n: int = 8) -> list[dict]:
    """Session selection: contrasts with misses first, the rest shuffled.
    Returns a flat [{contrast, tip, words, gloss}] with no repeated pairs."""
    groups = load_pairs(lang)
    if not groups:
        return []
    flat = [
        {"contrast": g["contrast"], "tip": g["tip"], "words": p["words"], "gloss": p["gloss"]}
        for g in groups
        for p in g["pairs"]
    ]
    priority = _failed_contrasts(user, lang)
    first = [p for p in flat if p["contrast"] in priority]
    rest = [p for p in flat if p["contrast"] not in priority]
    random.shuffle(first)
    random.shuffle(rest)
    return (first + rest)[:n]


def _key(word: str) -> str:
    return re.sub(r"[^\w]", "", word, flags=re.UNICODE).lower()


def verdict(expected: list[str], heard_words: list[str]) -> dict:
    """Compare the expected pair with the transcription (normalized keys).

    ok      -> both different words were heard, in order.
    same    -> the same word was heard twice (heard_as says which): the
               distinction was not perceived.
    unclear -> the pair was not recognized (noise, something else): repeat.
    """
    e1, e2 = _key(expected[0]), _key(expected[1])
    heard = [_key(w) for w in heard_words if _key(w)]
    relevant = [h for h in heard if h in (e1, e2)]
    if relevant[:2] == [e1, e2]:
        return {"status": "ok", "heard_as": None, "heard": heard}
    if len(relevant) >= 2 and relevant[0] == relevant[1]:
        return {"status": "same", "heard_as": relevant[0], "heard": heard}
    return {"status": "unclear", "heard_as": None, "heard": heard}


def record_attempt(
    user: str, lang: str, contrast: str, pair_label: str, distinguished: bool
) -> None:
    """Update (or create) the contrast's tally line in phonemes.md."""
    day = datetime.now().strftime("%Y-%m-%d")
    text = memory.read_phonemes(user, lang)
    lines = text.splitlines() if text else []
    if not lines:
        lines = ["# Phonemes and contrasts being tracked"]
    if not any(line.strip() == _SECTION for line in lines):
        lines += ["", _SECTION]
    key = f"{contrast} ({pair_label})"
    for i, ln in enumerate(lines):
        m = _TALLY_RE.match(ln.strip())
        if m and f"{m.group('contrast')} ({m.group('pair')})" == key:
            n, ok = int(m.group("n")) + 1, int(m.group("ok")) + (1 if distinguished else 0)
            lines[i] = f"- {key}: {n} attempts · {ok} distinguished · last {day}"
            break
    else:
        idx = lines.index(_SECTION) + 1
        n, ok = 1, (1 if distinguished else 0)
        lines.insert(idx, f"- {key}: {n} attempts · {ok} distinguished · last {day}")
    memory.write_phonemes(user, lang, "\n".join(lines).rstrip() + "\n")
