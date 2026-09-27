"""Read-aloud scoring (mode 4).

Aligns the reference text (what the learner was meant to read) with what the
speech-to-text model transcribed (with per-word confidence) and tags each
reference word:

- ok    : transcribed with high confidence (sounded clear).
- weak  : transcribed but with low confidence (sounded doubtful).
- miss  : the model heard something else or nothing (likely reading error).

Recognition confidence is a proxy for pronunciation clarity, not a phonetic
analysis. Good enough without a phoneme-level scoring model.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from . import config

_WORD_RE = re.compile(r"\S+")


def _key(surface: str) -> str:
    """Comparison key: lowercase, no punctuation (keeps unicode letters)."""
    return re.sub(r"[^\w]", "", surface, flags=re.UNICODE).lower()


def _ref_tokens(text: str) -> list[dict]:
    """Tokenize the reference into words with letters, keeping the original form."""
    out: list[dict] = []
    for m in _WORD_RE.finditer(text):
        surface = m.group(0)
        key = _key(surface)
        if key:  # drop punctuation-only tokens
            out.append({"surface": surface, "key": key})
    return out


def score_reading(reference: str, heard_words: list[dict]) -> dict:
    """Return the per-reference-word scoring plus a summary.

    `heard_words`: list of {word, probability, ...} from stt.transcribe_words.
    """
    ref = _ref_tokens(reference)
    heard: list[dict[str, Any]] = [
        {"key": _key(w.get("word", "")), "prob": w.get("probability")}
        for w in heard_words
        if _key(w.get("word", ""))
    ]

    ref_keys = [t["key"] for t in ref]
    heard_keys = [h["key"] for h in heard]

    # Status per reference word, "miss" by default.
    results: list[dict[str, Any]] = [
        {"text": t["surface"], "status": "miss", "heard": None, "prob": None} for t in ref
    ]

    sm = SequenceMatcher(a=ref_keys, b=heard_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                h = heard[j1 + k]
                prob = h["prob"]
                if prob is None or prob >= config.READ_WORD_PROB_OK:
                    status = "ok"
                elif prob >= config.READ_WORD_PROB_WEAK:
                    status = "weak"
                else:
                    status = "miss"
                results[i1 + k].update(status=status, heard=heard[j1 + k]["key"], prob=prob)
        elif tag == "replace":
            # Reference replaced by something else: mark it miss, record what was heard.
            heard_blob = " ".join(heard_keys[j1:j2]) or None
            for idx in range(i1, i2):
                results[idx].update(status="miss", heard=heard_blob)
        # delete (reference not heard) -> stays "miss" by default.
        # insert (extra words in the audio) -> ignored for display.

    n = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    weak = sum(1 for r in results if r["status"] == "weak")
    miss = sum(1 for r in results if r["status"] == "miss")
    accuracy = round(100 * ok / n) if n else 0

    # Words to reinforce (unique, in order): the weak/miss words that ARE in the
    # reference (they have a surface form), so correct audio can be offered.
    flagged: list[str] = []
    seen: set[str] = set()
    for r in results:
        if r["status"] in ("weak", "miss"):
            kk = _key(r["text"])
            if kk and kk not in seen:
                seen.add(kk)
                flagged.append(r["text"])

    return {
        "words": results,
        "summary": {
            "total": n,
            "ok": ok,
            "weak": weak,
            "miss": miss,
            "accuracy": accuracy,
        },
        "flagged": flagged,
    }
