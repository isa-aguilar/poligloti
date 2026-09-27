"""Score history and accumulation of resolved errors.

What is protected here is the answer to "have I improved?": without a time
series of scores and without accumulated resolved errors, the progress screen
can only show today's snapshot.
"""

import asyncio

import pytest

from backend import config, memory, post_session


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    memory.user_lang_dir("alex", "de")
    return tmp_path


def _scores(**over):
    base = dict.fromkeys(config.SKILL_KEYS, 40)
    base.update(over)
    return base


def test_history_accumulates_scores(mem):
    memory.write_skill_tracker(
        "alex", "de", "A1", _scores(grammar=30), ["dative"], [], history_note="First."
    )
    memory.write_skill_tracker(
        "alex", "de", "A1", _scores(grammar=45), ["dative"], [], history_note="Second."
    )
    hist = memory.read_skill_history("alex", "de")
    assert len(hist) == 2
    # Oldest to newest: what a chart expects.
    assert [h["scores"]["grammar"] for h in hist] == [30, 45]
    assert hist[0]["note"] == "First."
    assert set(hist[0]["scores"]) == set(config.SKILL_KEYS)


def test_frontmatter_reflects_the_latest(mem):
    memory.write_skill_tracker("alex", "de", "A1", _scores(grammar=30), [], [])
    memory.write_skill_tracker("alex", "de", "A2", _scores(grammar=45), [], [])
    tr = memory.read_skill_tracker("alex", "de")
    assert tr["cefr"] == "A2" and tr["scores"]["grammar"] == 45


def test_resolved_errors_accumulate(mem):
    memory.write_skill_tracker("alex", "de", "A1", _scores(), ["dative"], ["overusing sehr"])
    memory.write_skill_tracker("alex", "de", "A1", _scores(), ["dative"], ["participle of lesen"])
    tr = memory.read_skill_tracker("alex", "de")
    # The section used to be overwritten and the earlier achievement disappeared.
    assert tr["resolved_errors"] == ["overusing sehr", "participle of lesen"]


def test_resolved_error_that_reappears_stops_counting(mem):
    memory.write_skill_tracker("alex", "de", "A1", _scores(), [], ["overusing sehr"])
    memory.write_skill_tracker("alex", "de", "A1", _scores(), ["overusing sehr"], [])
    tr = memory.read_skill_tracker("alex", "de")
    assert tr["resolved_errors"] == []
    assert tr["active_errors"] == ["overusing sehr"]


def test_resolved_errors_are_not_duplicated(mem):
    memory.write_skill_tracker("alex", "de", "A1", _scores(), [], ["overusing sehr"])
    memory.write_skill_tracker("alex", "de", "A1", _scores(), [], ["Overusing sehr"])
    assert memory.read_skill_tracker("alex", "de")["resolved_errors"] == ["overusing sehr"]


def test_old_entries_without_scores_are_ignored(mem):
    """History written before scores were stored has no numbers: none are invented."""
    path = memory.user_lang_dir("alex", "de") / "skill-tracker.md"
    path.write_text(
        "---\ncefr: A1\n---\n\n## Active errors\n\n## Resolved errors\n\n"
        "## History\n### 2026-07-13 19:28\nBetter speaking fluency.\n",
        encoding="utf-8",
    )
    assert memory.read_skill_history("alex", "de") == []
    # From now on they are stored, without losing the old entry in the file.
    memory.write_skill_tracker("alex", "de", "A1", _scores(), [], [], history_note="New.")
    hist = memory.read_skill_history("alex", "de")
    assert len(hist) == 1 and hist[0]["note"] == "New."
    assert "Better speaking fluency." in path.read_text(encoding="utf-8")


def test_assessment_close_returns_the_result(monkeypatch, tmp_path):
    """The closing screen has to be able to show the level.

    Otherwise a learner who asks for her level during the assessment leaves
    without knowing it: the summary came out empty because the close only
    returned the file name.
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "sam" / "en" / "sessions").mkdir(parents=True)
    (tmp_path / "sam" / "en" / "sessions" / "2026-08-27.md").write_text(
        "## Turn\n- **Learner**: I like the beach\n", encoding="utf-8"
    )

    async def fake_analyst(*a, **k):
        return {
            "cefr": "A2-B1",
            "scores": dict.fromkeys(config.SKILL_KEYS, 60),
            "strengths": ["Listening"],
            "weaknesses": ["Verb tenses"],
            "focus": "Basic grammar",
            "milestones": ["Describe your day"],
            "summary": "Copes well in everyday conversation.",
        }

    monkeypatch.setattr(post_session, "_analyst_json", fake_analyst)
    out = asyncio.run(
        post_session._finalize_assessment(
            {"user": "sam", "lang": "en", "day": "2026-08-27", "turns": 5}
        )
    )
    assert out["cefr"] == "A2-B1"
    assert out["strengths"] == ["Listening"]
    assert out["weaknesses"] == ["Verb tenses"]
    assert out["focus"] == "Basic grammar"
    assert "everyday conversation" in out["assessment_summary"]


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_assessment_prompts_forbid_leaving_the_learner_hanging(lang):
    """No language may lose the rule about answering "what is my level?"."""
    path = config.PROMPTS_ROOT / lang / "mode-6-assessment" / "initial-assessment.md"
    text = path.read_text(encoding="utf-8")
    assert '"My progress"' in text, f"{path}: does not point to My progress when asked"
    assert "NEVER tell them you cannot" in text, f"{path}: does not explicitly forbid refusing"
