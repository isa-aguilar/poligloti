"""Regression tests for security hardening.

poligloti has no login (see PRIVACY.md), so these keep the damage small when
someone who should not reaches the port, or when a model answers something
unexpected.
"""

from __future__ import annotations

import asyncio

import pytest

from backend import cefr, memory, post_session
from tests.conftest import LEARNER
from tests.test_api import _start, client  # noqa: F401  (shared fixture)


def test_session_start_does_not_return_the_system_prompt(client):  # noqa: F811
    data = _start(client)
    assert "system_prompt" not in data
    # Not even fragments: the memory block carries the level from USER.md.
    assert "cefr_estimate" not in str(data)


# ---------------------------------------------------------------------------
# CEFR level: the analyst's free-text answer must never become a file path.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A1", "A1"),
        ("b2", "B2"),
        (" A2-B1 ", "A2-B1"),
        ("A2 - B1", "A2-B1"),
        ("B1-A2", "A2-B1"),
        # Stored values with decorations keep their level.
        ("B1+", "B1"),
        ("A2 (estimated)", "A2"),
        # What matters for safety: the output is always a level, never a path.
        ("../../../../outside/A1", "A1"),
        ("/etc/A1", "A1"),
        ("A2-B1\nbad: yes", "A2-B1"),
        ("A1 A2 B1", None),
        ("Z9", None),
        ("C3", None),
        ("B12", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_cefr_is_always_canonical(raw, expected):
    out = cefr.normalize_cefr(raw)
    assert out == expected
    if out:
        assert "/" not in out and "." not in out


@pytest.mark.parametrize("value", ["B1", "A2-B1"])
def test_is_canonical_accepts(value):
    assert cefr.is_canonical_cefr(value)


@pytest.mark.parametrize("value", ["b1", "B1+", "A2 - B1", "../A1", "", None])
def test_is_canonical_rejects(value):
    assert not cefr.is_canonical_cefr(value)


def _user_md(data_dir):
    return data_dir / LEARNER / "de" / "USER.md"


@pytest.mark.parametrize("value", ["../../../../outside/A1", "B1+", "Z9"])
def test_set_user_cefr_rejects_non_canonical_levels(data_dir, value):
    with pytest.raises(ValueError):
        memory.set_user_cefr(LEARNER, "de", value)
    assert memory.read_user_cefr_declared(LEARNER, "de") == "A2-B1"


def test_set_user_cefr_does_not_treat_the_level_as_a_regex(data_dir):
    memory.set_user_cefr(LEARNER, "de", "B1")
    assert memory.read_user_cefr_declared(LEARNER, "de") == "B1"


def test_a_corrupt_stored_level_reads_back_canonical(data_dir):
    _user_md(data_dir).write_text("---\ncefr_estimate: ../../x/A1\n---\n", encoding="utf-8")
    assert memory.read_user_cefr_declared(LEARNER, "de") == "A1"
    _user_md(data_dir).write_text("---\ncefr_estimate: whatever\n---\n", encoding="utf-8")
    assert memory.read_user_cefr_declared(LEARNER, "de") is None
    assert memory.read_user_cefr(LEARNER, "de") == memory.DEFAULT_CEFR


def test_a_decorated_stored_level_is_kept(data_dir):
    _user_md(data_dir).write_text("---\ncefr_estimate: B1+\n---\n", encoding="utf-8")
    assert memory.read_user_cefr_declared(LEARNER, "de") == "B1"


def test_write_level_test_never_writes_outside_its_folder(data_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        memory.write_level_test(LEARNER, "de", "../../../outside/A1", "A2", "x")
    with pytest.raises(ValueError):
        memory.write_level_test(LEARNER, "de", "A1", "/tmp/A2", "x")
    assert not list(outside.iterdir())


def _stub_analyst(monkeypatch, answer: dict) -> None:
    async def fake_analyst(*args, **kwargs):
        return answer

    monkeypatch.setattr(post_session, "_analyst_json", fake_analyst)
    monkeypatch.setattr(memory, "read_session_day", lambda *a, **kw: "Student: hello\n")


def test_assessment_keeps_only_the_level_from_a_poisoned_answer(data_dir, monkeypatch):
    _stub_analyst(monkeypatch, {"cefr": "../../../outside/A1", "scores": {}, "summary": "x"})
    session = {"user": LEARNER, "lang": "de", "mode": 6, "turns": 3, "day": None}
    out = asyncio.run(post_session._finalize_assessment(session))
    assert out["cefr"] == "A1"
    assert "cefr_estimate: A1\n" in _user_md(data_dir).read_text()


def test_assessment_without_a_level_keeps_the_previous_one(data_dir, monkeypatch):
    _stub_analyst(monkeypatch, {"cefr": "../../etc/passwd", "scores": {}, "summary": "x"})
    session = {"user": LEARNER, "lang": "de", "mode": 6, "turns": 3, "day": None}
    out = asyncio.run(post_session._finalize_assessment(session))
    assert out["cefr"] == "A2-B1"
    assert memory.read_user_cefr_declared(LEARNER, "de") == "A2-B1"


def test_level_up_with_a_corrupt_level_writes_inside_its_folder(data_dir, monkeypatch, tmp_path):
    _user_md(data_dir).write_text(
        "---\ncefr_estimate: ../../../outside/A1\n---\n", encoding="utf-8"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    _stub_analyst(monkeypatch, {"passed": False, "reason": "x"})
    session = {"user": LEARNER, "lang": "de", "turns": 3, "day": None, "target_cefr": "A2"}
    out = asyncio.run(post_session._finalize_levelup(session))
    assert (data_dir / LEARNER / "de" / "level-tests" / out["levelup"]).is_file()
    assert not list(outside.iterdir())
