"""Tests for the lesson suggestion (backend/suggestion.py). Rule-based only."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend import config, memory, srs, suggestion, syllabus, teacher

BASE = dict.fromkeys(config.SKILL_KEYS, 50)


@pytest.fixture()
def mem(monkeypatch, tmp_path, make_learner):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    make_learner(tmp_path, cefr="A2", languages=("de",))
    return tmp_path


def _tracker(scores):
    """State of a learner who HAS been assessed: tracker + assessment on disk.

    Both, because the suggestion looks at the assessment (not the tracker) to
    decide whether the initial one is due.
    """
    memory.write_skill_tracker("alex", "de", "A2", scores, [], [])
    memory.write_assessment("alex", "de", "# Initial assessment\n")


def test_assessment_when_there_is_no_assessment(mem):
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "assessment" and s["mode"] == 6


def test_assessment_even_if_a_tracker_exists(mem):
    """Level set by hand, assessment never done.

    The app used to consider the learner assessed and hid the card forever,
    leaving her no way to take the initial assessment.
    """
    memory.write_skill_tracker("alex", "de", "A2", BASE, [], [])
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "assessment" and s["mode"] == 6


def test_review_when_due(mem, monkeypatch):
    _tracker(BASE)
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: True)
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "review" and s["mode"] == 1


def test_srs_due(mem, monkeypatch):
    _tracker(BASE)
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: False)
    monkeypatch.setattr(srs, "due_payload", lambda u, lang: {"due_count": 7})
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "srs" and s["count"] == 7 and s["route"] == "/review"


def test_lesson_carries_topic_id(mem, monkeypatch):
    _tracker(BASE)
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: False)
    monkeypatch.setattr(srs, "due_payload", lambda u, lang: {"due_count": 0})
    monkeypatch.setattr(
        syllabus, "next_topic", lambda u, lang: {"id": "a1-01", "title": "Introductions"}
    )
    monkeypatch.setattr(syllabus, "last_lesson_date", lambda u, lang: None)
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "lesson" and s["mode"] == 9
    assert s["topic_id"] == "a1-01" and s["focus"] == "Introductions"


def test_weekly_focus(mem, monkeypatch):
    _tracker(BASE)
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: False)
    monkeypatch.setattr(srs, "due_payload", lambda u, lang: {"due_count": 0})
    monkeypatch.setattr(syllabus, "next_topic", lambda u, lang: None)  # isolates the focus rule
    memory.write_curriculum("alex", "de", "B1", "Practise the dative at the market", [], [])
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "focus" and s["mode"] == 1 and "dative" in s["focus"]


def test_weak_skill(mem, monkeypatch):
    scores = dict(BASE)
    scores["pronunciation"] = 20
    _tracker(scores)
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: False)
    monkeypatch.setattr(srs, "due_payload", lambda u, lang: {"due_count": 0})
    monkeypatch.setattr(syllabus, "next_topic", lambda u, lang: None)  # isolates the skill rule
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "skill" and s["skill"] == "pronunciation" and s["mode"] == 4


def test_home_endpoint(mem, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "AUDIO_ROOT", tmp_path / "audio")
    (tmp_path / "audio").mkdir(exist_ok=True)
    from backend.app import app

    client = TestClient(app)
    r = client.get("/suggestion/alex/de")
    assert r.status_code == 200
    data = r.json()
    assert "greeting" in data and "suggestion" in data
    assert data["greeting"]["name"] == "Alex"
    assert data["suggestion"]["kind"] == "assessment"  # no tracker
    # invalid language -> 400 (validate_ids)
    assert client.get("/suggestion/alex/xx").status_code == 400


def test_greeting_name_comes_from_the_profile(mem):
    profile = mem / "alex" / "profile.md"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("name: Alex", "name: Alexandra"),
        encoding="utf-8",
    )
    assert suggestion.build_greeting("alex", "de")["name"] == "Alexandra"
    # Without a profile the capitalized id is used.
    assert suggestion.build_greeting("sam", "de")["name"] == "Sam"


def test_streak_and_words(mem):
    sd = memory.user_lang_dir("alex", "de") / "sessions"
    today = datetime.now().date()
    for delta in (0, 1, 2):  # today, yesterday, the day before -> streak 3
        (sd / f"{today - timedelta(days=delta)}.md").write_text("# s\n", encoding="utf-8")
    # gap: does not count
    (sd / f"{today - timedelta(days=4)}.md").write_text("# s\n", encoding="utf-8")
    memory.append_vocab("alex", "de", "\n## x\n- **die Reise**: trip\n- **der Zug**: train\n")
    g = suggestion.build_greeting("alex", "de")
    assert g["streak"] == 3 and g["vocab_count"] == 2 and g["name"] == "Alex"


def test_greeting_without_measured_level_does_not_invent_one(mem):
    """A learner starting a new language must not see a level nobody measured.

    It used to show "A2-B1" by default, contradicting the card on the same
    screen that suggested taking the initial assessment.
    """
    (config.DATA_DIR / "alex" / "fr").mkdir(parents=True)
    assert suggestion.build_greeting("alex", "fr")["cefr"] is None
    # The declared level is shown.
    assert suggestion.build_greeting("alex", "de")["cefr"] == "A2"


def test_greeting_prefers_the_tracker_level(mem):
    _tracker(BASE)
    assert suggestion.build_greeting("alex", "de")["cefr"] == "A2"


def test_internal_level_still_has_a_value(mem):
    """The engine needs a CEFR level to compute with even when none exists."""
    (config.DATA_DIR / "alex" / "fr").mkdir(parents=True)
    assert memory.read_user_cefr("alex", "fr") == memory.DEFAULT_CEFR
    assert memory.read_user_cefr_declared("alex", "fr") is None
