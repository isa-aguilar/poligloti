"""Built system prompts: no placeholder left behind, limits follow the config."""

from __future__ import annotations

import re

import pytest

from backend import config, prompt_builder

_PLACEHOLDER = re.compile(r"__[A-Z_]+__")


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
@pytest.mark.parametrize("mode", [1, 2, 3, 4, 5, 7, 8, 9])
def test_mode_prompts_have_no_placeholder_left(data_dir, lang, mode):
    prompt = prompt_builder.build_system_prompt("alex", lang, mode, "## Learner memory")
    assert not _PLACEHOLDER.findall(prompt)
    assert config.LANG_NAMES[lang] in prompt


@pytest.mark.parametrize("lang", config.SUPPORTED_LANGS)
@pytest.mark.parametrize("sub_mode", ["assessment", "weekly_review", "test"])
def test_assessment_prompts_have_no_placeholder_left(data_dir, lang, sub_mode):
    prompt = prompt_builder.build_mode6_prompt("alex", lang, sub_mode, "## Learner memory")
    assert not _PLACEHOLDER.findall(prompt)


def test_correction_limit_follows_config(data_dir, monkeypatch):
    monkeypatch.setattr(config, "MAX_CORRECTIONS", 2)
    prompt = prompt_builder.build_system_prompt("alex", "de", 1, "")
    assert "At most 2 corrections per turn" in prompt
    assert "At most 3" not in prompt


def test_colleague_prompts_have_no_placeholder_left(data_dir):
    for lang in config.SUPPORTED_LANGS:
        for sub in ("email", "chat"):
            prompt = prompt_builder.build_colleague_prompt("alex", lang, sub, "Weekly sync")
            assert not _PLACEHOLDER.findall(prompt)
