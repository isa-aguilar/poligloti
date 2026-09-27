"""AI configuration: no default models, STT and TTS inherit the chat endpoint."""

from __future__ import annotations

import importlib

import pytest

from backend import config

_AI_VARS = [
    "AI_BASE_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_VISION_MODEL",
    "STT_BASE_URL",
    "STT_API_KEY",
    "STT_MODEL",
    "STT_WORD_TIMESTAMPS",
    "TTS_BASE_URL",
    "TTS_API_KEY",
    "TTS_MODEL",
    "TTS_VOICE_DE",
    "TTS_VOICE_EN",
    "TTS_VOICE_FR",
    "SUPPORT_LANG",
    "DATA_DIR",
]


@pytest.fixture
def reload_config(monkeypatch):
    """Reload backend.config with a controlled environment, then restore it."""
    monkeypatch.setenv("POLIGLOTI_SKIP_DOTENV", "1")
    for var in _AI_VARS:
        monkeypatch.delenv(var, raising=False)

    def _reload(**env: str):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    monkeypatch.setenv("POLIGLOTI_SKIP_DOTENV", "1")
    for var in _AI_VARS:
        monkeypatch.delenv(var, raising=False)
    importlib.reload(config)


def test_no_default_models_or_endpoints(reload_config):
    cfg = reload_config()
    assert cfg.AI_BASE_URL == ""
    assert cfg.AI_MODEL == ""
    assert cfg.STT_MODEL == ""
    assert cfg.TTS_MODEL == ""
    assert all(spec["voices"] == [] for spec in cfg.LANGUAGES.values())


def test_stt_and_tts_inherit_the_chat_endpoint_and_key(reload_config):
    cfg = reload_config(AI_BASE_URL="https://api.example.com/v1/", AI_API_KEY="k1")
    assert cfg.AI_BASE_URL == "https://api.example.com/v1"
    assert cfg.STT_BASE_URL == cfg.AI_BASE_URL
    assert cfg.TTS_BASE_URL == cfg.AI_BASE_URL
    assert cfg.STT_API_KEY == "k1"
    assert cfg.TTS_API_KEY == "k1"


def test_each_service_can_have_its_own_endpoint(reload_config):
    cfg = reload_config(
        AI_BASE_URL="https://chat.example.com/v1",
        AI_API_KEY="chat-key",
        STT_BASE_URL="http://localhost:8000/v1",
        STT_API_KEY="",
        TTS_BASE_URL="http://localhost:8001/v1",
        TTS_API_KEY="voice-key",
    )
    assert cfg.STT_BASE_URL == "http://localhost:8000/v1"
    # An empty STT key falls back to the chat key: a local server ignores it.
    assert cfg.STT_API_KEY == "chat-key"
    assert cfg.TTS_BASE_URL == "http://localhost:8001/v1"
    assert cfg.TTS_API_KEY == "voice-key"


def test_voices_per_language_first_is_default(reload_config):
    cfg = reload_config(TTS_VOICE_DE="voice-a, voice-b", TTS_VOICE_FR="voice-c")
    assert cfg.LANGUAGES["de"]["voices"] == ["voice-a", "voice-b"]
    assert cfg.LANGUAGES["fr"]["voices"] == ["voice-c"]
    assert cfg.LANGUAGES["en"]["voices"] == []


def test_unknown_support_language_falls_back_to_english(reload_config):
    assert reload_config(SUPPORT_LANG="xx").SUPPORT_LANG == "en"
    assert reload_config(SUPPORT_LANG="es").SUPPORT_LANG == "es"


def test_relative_data_dir_is_relative_to_the_repo(reload_config):
    cfg = reload_config(DATA_DIR="some/where")
    assert (cfg.REPO_ROOT / "some" / "where").resolve() == cfg.DATA_DIR
