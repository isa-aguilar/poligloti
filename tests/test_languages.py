"""Completeness tests for every supported language.

Parametrized over config.SUPPORTED_LANGS on purpose: when a new language is
added, these tests demand on their own that it arrives complete (config + 13
prompts + the three seeds + scenario sections), without touching anything
here. It is the lock against a half-populated language.
"""

from __future__ import annotations

import pytest

from backend import config, minimal_pairs, scenarios, syllabus
from backend.prompt_builder import MODE6_FILES, MODE_FILES
from backend.services import tts


def test_supported_languages():
    assert config.SUPPORTED_LANGS == ("de", "en", "fr")
    assert config.LANG_NAMES == {"de": "German", "en": "English", "fr": "French"}


def test_default_voice_is_the_first_configured_one(monkeypatch):
    """The language default is the first voice of TTS_VOICE_<LANG>, and a voice
    outside the list is never allowed."""
    monkeypatch.setitem(config.LANGUAGES, "fr", {"name": "French", "voices": ["v1", "v2"]})
    assert tts.voice_for("fr") == "v1"
    assert tts.allowed_voices("fr") == ["v1", "v2"]
    monkeypatch.setitem(config.LANGUAGES, "fr", {"name": "French", "voices": []})
    assert tts.voice_for("fr") is None
    assert tts.allowed_voices("fr") == []


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_all_prompts_per_language(lang):
    """The 13 prompt files exist and are not empty for every language."""
    root = config.PROMPTS_ROOT / lang
    files = list(MODE_FILES.values())
    files += [f"mode-5-colleague-{sub}.md" for sub in ("email", "chat")]
    files += [f"mode-6-assessment/{f}" for f in MODE6_FILES.values()]
    assert len(files) == 13
    for rel in files:
        path = root / rel
        assert path.is_file(), f"missing {path}"
        assert path.read_text(encoding="utf-8").strip(), f"empty: {path}"


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_minimal_pairs_seed_loads(lang):
    groups = minimal_pairs.load_pairs(lang)
    assert len(groups) >= 8
    for g in groups:
        assert g["contrast"] and g["tip"], g
        assert len(g["pairs"]) >= 2, g["contrast"]


def test_minimal_pairs_fr_key_contrast():
    """The /y/-/u/ contrast (tu/tout) is a must for Spanish and English speakers."""
    groups = minimal_pairs.load_pairs("fr")
    words = {tuple(p["words"]) for g in groups for p in g["pairs"]}
    assert ("tu", "tout") in words or ("tout", "tu") in words


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_syllabus_seed_loads(lang):
    syllabus.load_syllabus.cache_clear()
    data = syllabus.load_syllabus(lang)
    total = sum(len(topics) for topics in data.values())
    assert "A1" in data and total >= 20, f"{lang}: {total} topics"
    for topics in data.values():
        for t in topics:
            assert t["id"] and t["title"] and t["grammar"], t


def test_syllabus_fr_covers_a1_to_b2():
    syllabus.load_syllabus.cache_clear()
    data = syllabus.load_syllabus("fr")
    assert set(data.keys()) >= {"A1", "A2", "B1", "B2"}
    total = sum(len(topics) for topics in data.values())
    assert total >= 35, f"the fr syllabus has {total} topics, 35+ expected"


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_expressions_seed_exists(lang):
    path = config.PROMPTS_ROOT / "expressions" / f"{lang}.md"
    assert path.is_file() and path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
def test_scenarios_complete_per_language(lang, data_dir):
    """Every scenario must carry register, vocabulary and phrases for the language.

    The gap this closes: a newly added language can leave scenarios without its
    sections, and the role-play then starts with no register and no vocabulary,
    without any error. A language half supported in the scenarios must not pass
    silently again.
    """
    listed = scenarios.list_scenarios()
    assert len(listed) >= 12
    for s in listed:
        block, info = scenarios.build_block(s["id"], lang)
        sid = f"{s['id']} [{lang}]"
        assert info["register"], f"no register: {sid}"
        assert len(info["vocab"]) >= 8, f"short vocabulary: {sid}"
        assert len(info["phrases"]) >= 5, f"too few phrases: {sid}"
        # The language suffix is stripped and no other language's content leaks in.
        for tag in (f"({code})" for code in config.SUPPORTED_LANGS):
            assert tag not in block, f"unfiltered suffix {tag} in {sid}"


def test_scenario_ids_and_categories(data_dir):
    # data_dir: an empty DATA_DIR, so a developer's own scenarios do not count.
    ids = {s["id"] for s in scenarios.list_scenarios()}
    assert {"work/kpi-meeting", "everyday/supermarket"} <= ids
    assert {i.split("/")[0] for i in ids} == {"work", "everyday"}
