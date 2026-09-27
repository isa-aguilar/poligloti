"""Third STT anti-contamination layer: `stt_hints` are not vocabulary.

When speech-to-text mishears a proper name, the teacher "corrects" it and that
false correction is persisted as if it were the learner's mistake,
contaminating the following sessions.

There were already two defences (the transcription prompt and the mode 4
caveat). This is the third and last one: when the session closes, any
vocabulary term matching a proper name from the profile is dropped before it
is written to `vocab.md`.
"""

import asyncio

import pytest

from backend import config, post_session

PROFILE = (
    "---\n"
    "name: Alex\n"
    "languages_studied: [de]\n"
    "primary_language: de\n"
    "stt_hints: [Alex, Bankhof, Northwind]\n"
    "---\n"
    "# Profile\n"
)


@pytest.fixture()
def mem(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "alex" / "de" / "sessions").mkdir(parents=True)
    (tmp_path / "alex" / "profile.md").write_text(PROFILE, encoding="utf-8")
    (tmp_path / "alex" / "de" / "sessions" / "2026-08-28.md").write_text(
        "## Turn\n- **Learner**: Ich fahre zum Bankhof\n", encoding="utf-8"
    )
    return tmp_path


async def _noop():
    return None


def _close(monkeypatch, vocab, captured=None):
    """Run the session close with a fake analyst and return its result."""

    async def fake_analyst(instruction, payload, **kw):
        if captured is not None:
            captured.append(instruction)
        return {
            "progress_note": "Test session.",
            "vocab": vocab,
            "missed_opportunities": [],
        }

    monkeypatch.setattr(post_session, "_analyst_json", fake_analyst)
    # Only the initial assessment creates the tracker; without it the pass is skipped.
    monkeypatch.setattr(post_session, "_update_skill_tracker", lambda s: _noop())
    return asyncio.run(
        post_session._post_session_pass(
            {"user": "alex", "lang": "de", "day": "2026-08-28", "turns": 1, "mode": 1}
        )
    )


def test_drops_vocab_that_is_a_proper_name(mem, monkeypatch):
    """`Bankhof` is a hint (what speech-to-text hears for `Bahnhof`): dropped."""
    res = _close(
        monkeypatch,
        [
            {"term": "Bankhof", "translation": "??"},
            {"term": "der Bahnhof", "translation": "the station"},
        ],
    )
    saved = (mem / "alex" / "de" / "vocab.md").read_text(encoding="utf-8")
    assert "Bahnhof" in saved
    assert "Bankhof" not in saved
    assert res["vocab_added"] == 1


def test_hint_is_recognized_despite_case_or_article(mem, monkeypatch):
    """The comparison is normalized, like the vocabulary dedup."""
    res = _close(
        monkeypatch,
        [{"term": "das Bankhof", "translation": "??"}, {"term": "NORTHWIND", "translation": "??"}],
    )
    # Both are filtered, so nothing is written: vocab.md may not even exist.
    assert res["vocab_added"] == 0
    path = mem / "alex" / "de" / "vocab.md"
    if path.exists():
        saved = path.read_text(encoding="utf-8")
        assert "Bankhof" not in saved and "NORTHWIND" not in saved


def test_legitimate_vocab_is_untouched(mem, monkeypatch):
    """Without matching hints, the close behaves as usual."""
    res = _close(monkeypatch, [{"term": "die Reise", "translation": "the trip"}])
    assert "Reise" in (mem / "alex" / "de" / "vocab.md").read_text(encoding="utf-8")
    assert res["vocab_added"] == 1


def test_hints_are_also_given_to_the_analyst(mem, monkeypatch):
    """Cheap defence in the prompt, on top of the code filter."""
    captured = []
    _close(monkeypatch, [], captured=captured)
    assert captured, "the analyst was not called"
    instruction = captured[0]
    assert "proper names" in instruction
    for hint in ("bankhof", "northwind", "alex"):
        assert hint in instruction.lower(), hint


def test_without_stt_hints_nothing_is_filtered(monkeypatch, tmp_path):
    """A profile without hints must not break the close."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "sam" / "en" / "sessions").mkdir(parents=True)
    (tmp_path / "sam" / "profile.md").write_text("---\nname: Sam\n---\n", encoding="utf-8")
    (tmp_path / "sam" / "en" / "sessions" / "2026-08-28.md").write_text(
        "## Turn\n- **Learner**: hi\n", encoding="utf-8"
    )

    async def fake_analyst(instruction, payload, **kw):
        return {
            "progress_note": "ok",
            "vocab": [{"term": "trip", "translation": "journey"}],
            "missed_opportunities": [],
        }

    monkeypatch.setattr(post_session, "_analyst_json", fake_analyst)
    monkeypatch.setattr(post_session, "_update_skill_tracker", lambda s: _noop())
    res = asyncio.run(
        post_session._post_session_pass(
            {"user": "sam", "lang": "en", "day": "2026-08-28", "turns": 1, "mode": 1}
        )
    )
    assert res["vocab_added"] == 1
