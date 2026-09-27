"""Shared test setup.

The environment is cleaned BEFORE the backend is imported: a developer's real
`.env` must never be loaded in tests, and no AI endpoint variable may leak in,
so no test can reach a real model server by accident.
"""

import os

os.environ["POLIGLOTI_SKIP_DOTENV"] = "1"
for _name in list(os.environ):
    if _name.startswith(("AI_", "STT_", "TTS_")):
        del os.environ[_name]

import pytest  # noqa: E402

from backend import config  # noqa: E402

LEARNER = "alex"


def make_learner(
    root, user: str = LEARNER, lang: str = "de", cefr: str = "A2-B1", languages=("de", "en")
) -> None:
    """Create a learner on disk: profile.md plus USER.md for `lang`."""
    udir = root / user
    (udir / lang / "sessions").mkdir(parents=True, exist_ok=True)
    (udir / "profile.md").write_text(
        "---\n"
        f"name: {user.capitalize()}\n"
        f"languages_studied: [{', '.join(languages)}]\n"
        f"primary_language: {languages[0]}\n"
        "ui_language: en\n"
        "---\n",
        encoding="utf-8",
    )
    (udir / lang / "USER.md").write_text(
        f"---\ncefr_estimate: {cefr}\n---\n# {user.capitalize()}\n", encoding="utf-8"
    )


@pytest.fixture(name="make_learner")
def make_learner_fixture():
    """The `make_learner` helper, for tests that need more than one learner."""
    return make_learner


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A temporary DATA_DIR with the learner "alex" (German) already created."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    make_learner(tmp_path)
    return tmp_path
