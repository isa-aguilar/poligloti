"""Incremental extractor of the `reply` field from the model's JSON stream.

The model emits a JSON object whose FIRST field is `reply` (a string in the
target language, the part that is spoken aloud). As stream deltas arrive, this
class locates the `reply` value and splits it into sentences ready for TTS,
without waiting for the JSON to close. That lets speech synthesis start as soon
as the first sentence exists instead of after the whole completion (the model
dominates wall-clock time).

Boundary detection: `.!?…` characters outside an escape sequence, with a
minimum length guard so abbreviations (z.B., etc.) are not cut into tiny clips.
The raw value is kept escaped and decoded with `json.loads` to produce the clean
text sent to TTS (handles \\n, \\", \\uXXXX robustly).

If the model emits no JSON with `reply`, `feed()` returns nothing and the caller
must fall back to synthesizing the whole raw text at the end.
"""

from __future__ import annotations

import json
import re

_KEY_RE = re.compile(r'"reply"\s*:\s*"')
_DEFAULT_BOUNDARIES = ".!?…"


class ReplyStreamExtractor:
    """Consume stream deltas and emit `reply` sentences ready for TTS."""

    def __init__(self, min_chunk_chars: int = 25, boundaries: str = _DEFAULT_BOUNDARIES):
        self._raw = ""  # everything received (to find the key and to fall back)
        self._cursor = 0  # next unprocessed index in _raw
        self._in_value = False  # the opening of the reply value was found
        self._closed = False  # the closing quote of the value was seen
        self._escape = False  # previous char was a backslash (inside the value)
        self._seg = ""  # raw (escaped) chars of the pending segment
        self._min = min_chunk_chars
        self._boundaries = set(boundaries)

    @property
    def raw(self) -> str:
        return self._raw

    @property
    def found_reply(self) -> bool:
        return self._in_value

    def feed(self, delta: str) -> list[str]:
        """Feed one stream delta. Returns the complete sentences that are ready."""
        self._raw += delta
        return self._process()

    def finish(self) -> str | None:
        """Close the stream. Returns the pending tail of the reply, if any."""
        if not self._seg:
            return None
        decoded = self._decode(self._seg)
        self._seg = ""
        if decoded is None:
            return None
        decoded = decoded.strip()
        return decoded or None

    # -- internals ---------------------------------------------------------
    def _process(self) -> list[str]:
        chunks: list[str] = []
        if not self._in_value:
            m = _KEY_RE.search(self._raw, self._cursor)
            if not m:
                return chunks
            self._in_value = True
            self._cursor = m.end()
        if self._closed:
            return chunks

        i = self._cursor
        n = len(self._raw)
        while i < n:
            ch = self._raw[i]
            if self._escape:
                self._seg += ch
                self._escape = False
                i += 1
                continue
            if ch == "\\":
                self._seg += ch
                self._escape = True
                i += 1
                continue
            if ch == '"':
                self._closed = True
                i += 1
                break
            self._seg += ch
            if ch in self._boundaries:
                chunk = self._maybe_flush()
                if chunk:
                    chunks.append(chunk)
            i += 1
        self._cursor = i
        return chunks

    def _maybe_flush(self) -> str | None:
        decoded = self._decode(self._seg)
        if decoded is None:
            return None  # incomplete escape: wait for more deltas
        if len(decoded.strip()) < self._min:
            return None  # too short (e.g. "z.B."): keep accumulating
        self._seg = ""
        return decoded.strip()

    @staticmethod
    def _decode(seg: str) -> str | None:
        try:
            return json.loads('"' + seg + '"')
        except json.JSONDecodeError:
            return None
