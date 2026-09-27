"""Robust parsing of the model output into the teacher contract.

The model (ideally) returns a JSON object with reply/corrections/new_vocab/
suggested_followup. Sometimes it wraps it in ``` or puts prose before it, and
sometimes it drifts into a hybrid markdown format ("**corrections**: [...]")
without a `reply` key. This module extracts the contract's JSON object; if the
model drifted to another format, it trims the contract tail off `reply` (so the
teacher does not read it aloud) and salvages the fields of the drifted format.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

from . import config

# Contract labels the model sometimes dumps as plain text after the reply when it
# does NOT emit the proper JSON object (drift to markdown / loose keys).
_CONTRACT_LABELS = ("corrections", "new_vocab", "suggested_followup", "revised")


def _iter_json_objects(text: str):
    """Iterate over balanced top-level JSON objects in `text`.

    Starts at every non-nested `{`, finds its balanced close while respecting
    strings and escapes, and continues after the object. Invalid blobs are skipped.
    """
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escaped = False
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    with contextlib.suppress(json.JSONDecodeError):
                        yield json.loads(text[i : j + 1])
                    break
            j += 1
        i = j + 1


def extract_json_object(text: str, prefer_key: str | None = None) -> dict | None:
    """Balanced JSON object in `text`.

    With `prefer_key`, returns the first top-level object that contains that key
    (avoids grabbing an inner object, e.g. a correction, when the real contract
    with `reply` comes later). If none has it, returns the first valid one.
    Without `prefer_key`, returns the first valid object.
    """
    first: dict | None = None
    for obj in _iter_json_objects(text):
        if not isinstance(obj, dict):
            continue
        if first is None:
            first = obj
        if prefer_key is None or prefer_key in obj:
            return obj
    return first


def _contract_tail_start(text: str) -> int:
    """Index where the contract tail starts (markdown label `**x**` or quoted key
    `"x"`) in drifted output. -1 if there is none."""
    best = -1
    for label in _CONTRACT_LABELS:
        for pat in (f"**{label}**", f'"{label}"'):
            idx = text.find(pat)
            if idx != -1 and (best == -1 or idx < best):
                best = idx
    return best


def _strip_contract_tail(text: str) -> str:
    """Cut the reply at the first contract label dumped as text."""
    idx = _contract_tail_start(text)
    return (text[:idx] if idx != -1 else text).strip()


def _after_label(text: str, label: str) -> str | None:
    """Text right after `**label**:` or `"label":`."""
    for pat in (f"**{label}**", f'"{label}"'):
        idx = text.find(pat)
        if idx == -1:
            continue
        rest = text[idx + len(pat) :].lstrip()
        if rest.startswith(":"):
            rest = rest[1:].lstrip()
        return rest
    return None


def _salvage_array(text: str, label: str) -> Any:
    """Salvage the JSON array after a label in drifted output."""
    rest = _after_label(text, label)
    if not rest or not rest.startswith("["):
        return None
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(rest):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(rest[: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _salvage_scalar(text: str, label: str) -> str:
    """Salvage a scalar (string) value after a label in drifted output."""
    rest = _after_label(text, label)
    if not rest:
        return ""
    if rest.startswith('"'):
        out: list[str] = []
        escaped = False
        for ch in rest[1:]:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                break
            out.append(ch)
        try:
            return json.loads('"' + "".join(out) + '"').strip()
        except json.JSONDecodeError:
            return "".join(out).strip()
    return rest.splitlines()[0].strip()


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


_TRAILING_PARENS = re.compile(r"\s*\([^()]*\)\s*$")
# Any short trailer ending in "!" ("Great!", "Sehr gut!", "Muy bien!"). It is
# language agnostic on purpose: the praise can come in the target language or
# in the support language.
_TRAILING_PRAISE = re.compile(r"(?:^|[.!?])\s*[^.!?]{1,25}!\s*$")


def _strip_trailing_praise(text: str) -> str:
    """Remove a trailing parenthesis or a short tag ending in '!'.

    The model sometimes "corrects" by returning the learner's sentence with
    praise attached ("Ich bin zwanzig. Sehr gut!", "... (great!)"). That is not
    a correction. The trim is deliberately narrow (a parenthesis, or a tag of
    under 25 characters ending in an exclamation mark) so it does not destroy a
    legitimate correction that only ADDS a missing word.
    """
    t = text.strip()
    for _ in range(2):  # it may carry both
        trimmed = _TRAILING_PRAISE.sub("", _TRAILING_PARENS.sub("", t)).strip()
        if trimmed == t or not trimmed:
            break
        t = trimmed
    return t


def _is_noop(correction: dict) -> bool:
    """A correction that corrects nothing: `original` and `corrected` are the
    same sentence (ignoring case, spaces, final punctuation and attached praise).

    It happens when the model means "this was already fine" but puts it in the
    wrong field, and the learner then sees a red correction card on a sentence
    of hers that was correct. Filtered for every language.
    """
    # The inverted marks cover a Spanish support language.
    a = _strip_trailing_praise(correction["original"]).strip(".!?\u00bf\u00a1 ").casefold()
    b = _strip_trailing_praise(correction["corrected"]).strip(".!?\u00bf\u00a1 ").casefold()
    return bool(a) and a == b


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def drop_stale_corrections(corrections: list[dict], said: str) -> list[dict]:
    """Drop corrections that quote something the learner did NOT just say.

    The model sometimes re-emits the previous turn's correction (it is in the
    history as part of its own earlier answer) or invents an `original`. Either
    way the learner sees a correction of a sentence she never wrote, often for
    something already corrected.

    Rule: a quote may only contain words she said. Every word of `original`
    must appear in what she just said. That lets PARTIAL quotes through (they
    are legitimate and frequent: correcting part of the sentence) and those
    that only change case or punctuation, but it blocks the case where the
    model misquotes her, changing exactly the word it claims is wrong. A
    correction without `original` (note only) is kept.
    """
    said_words = {w.casefold() for w in _WORD_RE.findall(said or "")}
    if not said_words:
        return corrections
    out = []
    for c in corrections:
        quoted = [w.casefold() for w in _WORD_RE.findall(c.get("original", ""))]
        if not quoted:
            out.append(c)
            continue
        if all(w in said_words for w in quoted):
            out.append(c)
    return out


def _norm_corrections(raw: Any) -> list[dict]:
    out: list[dict] = []
    for item in _as_list(raw)[: config.MAX_CORRECTIONS]:
        if isinstance(item, dict):
            out.append(
                {
                    "original": str(item.get("original", "")).strip(),
                    "corrected": str(item.get("corrected", "")).strip(),
                    "note": str(item.get("note", "")).strip(),
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"original": "", "corrected": "", "note": item.strip()})
    return [c for c in out if (c["corrected"] or c["note"]) and not _is_noop(c)]


def _norm_vocab(raw: Any) -> list[dict]:
    out: list[dict] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            term = str(item.get("term", "")).strip()
            if not term:
                continue
            out.append(
                {
                    "term": term,
                    "translation": str(item.get("translation", "")).strip(),
                    "example": str(item.get("example", "")).strip(),
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"term": item.strip(), "translation": "", "example": ""})
    return out


def parse_teacher_reply(content: str) -> dict:
    """Normalize the model output into the turn contract."""
    data = extract_json_object(content, prefer_key="reply")
    if data and "reply" in data:
        reply = str(data.get("reply", "")).strip()
        corrections = _norm_corrections(data.get("corrections"))
        new_vocab = _norm_vocab(data.get("new_vocab"))
        followup = str(data.get("suggested_followup", "")).strip()
        revised = str(data.get("revised", "")).strip()
    else:
        # The model did not emit the contract's JSON object (drift to markdown or
        # another format). Trim the contract tail so the teacher does not read the
        # JSON aloud, and salvage the drifted fields if there are any.
        reply = _strip_contract_tail(content)
        corrections = _norm_corrections(_salvage_array(content, "corrections"))
        new_vocab = _norm_vocab(_salvage_array(content, "new_vocab"))
        followup = _salvage_scalar(content, "suggested_followup")
        revised = _salvage_scalar(content, "revised")
    if not reply:
        reply = content.strip()
    return {
        "reply": reply,
        "corrections": corrections,
        "new_vocab": new_vocab,
        "suggested_followup": followup,
        # Only mode 5 feedback emits it (the full corrected draft).
        # Empty in every other mode.
        "revised": revised,
    }
