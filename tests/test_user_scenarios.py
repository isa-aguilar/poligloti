"""Scenarios added by users, in the shared data folder.

The base library is versioned with the code and adding one needs a deploy. The
ones in `<DATA_DIR>/_shared/scenarios/` are read from disk on every request:
adding a topic means dropping a file.
"""

import pytest

from backend import config, scenarios

SHEET = """---
title: Science homework
description: Help your child with a school worksheet in English.
level: A1
---

## Context

__USER_NAME__ helps their 6-year-old with a Science worksheet.

## Your role

You are the teacher and you guide the conversation.
"""


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "PROMPTS_ROOT", tmp_path / "prompts")
    base = tmp_path / "prompts" / "scenarios" / "everyday"
    base.mkdir(parents=True)
    (base / "supermarket.md").write_text(
        "---\ntitle: At the supermarket\n---\n\n## Context\n\nShopping.\n", encoding="utf-8"
    )
    mine = tmp_path / "data" / "_shared" / "scenarios" / "school"
    mine.mkdir(parents=True)
    return base, mine


def test_user_scenario_shows_up_in_the_list(roots):
    _, mine = roots
    (mine / "science-homework.md").write_text(SHEET, encoding="utf-8")
    ids = {s["id"] for s in scenarios.list_scenarios()}
    assert ids == {"everyday/supermarket", "school/science-homework"}


def test_user_scenario_can_be_loaded(roots):
    _, mine = roots
    (mine / "science-homework.md").write_text(SHEET, encoding="utf-8")
    block, info = scenarios.build_block("school/science-homework", "en")
    assert info["title"] == "Science homework"
    assert "Science worksheet" in block


def test_user_scenario_wins_over_the_library(roots, tmp_path):
    """Same id in both roots: the user's one wins, without duplicates."""
    own = tmp_path / "data" / "_shared" / "scenarios" / "everyday"
    own.mkdir(parents=True)
    (own / "supermarket.md").write_text(
        "---\ntitle: My supermarket\n---\n\n## Context\n\nMine.\n", encoding="utf-8"
    )
    listing = scenarios.list_scenarios()
    assert [s["id"] for s in listing].count("everyday/supermarket") == 1
    assert (
        next(s for s in listing if s["id"] == "everyday/supermarket")["title"] == "My supermarket"
    )


def test_invalid_id_still_rejected(roots):
    for bad in ("../secret", "everyday/../../etc/passwd", "", "UPPER/x"):
        with pytest.raises(scenarios.ScenarioNotFound):
            scenarios.build_block(bad, "en")


def test_missing_user_folder_does_not_crash(tmp_path, monkeypatch):
    """The shared data folder may not exist yet."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "PROMPTS_ROOT", tmp_path / "prompts")
    base = tmp_path / "prompts" / "scenarios" / "everyday"
    base.mkdir(parents=True)
    (base / "supermarket.md").write_text("---\ntitle: At the supermarket\n---\n", encoding="utf-8")
    assert [s["id"] for s in scenarios.list_scenarios()] == ["everyday/supermarket"]
