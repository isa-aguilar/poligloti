"""Graceful degradation through the API: a missing AI service is a clear, typed
answer, never a 500 and never an invented reply."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import config
from backend.services import AIServiceError, llm, status, stt, tts

REPLY = json.dumps(
    {"reply": "Hallo Alex!", "corrections": [], "new_vocab": [], "suggested_followup": "Und du?"}
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    learner = tmp_path / "alex"
    (learner / "de").mkdir(parents=True)
    (learner / "profile.md").write_text(
        "---\nname: Alex\nlanguages_studied: [de]\nprimary_language: de\n---\n", encoding="utf-8"
    )
    (learner / "de" / "USER.md").write_text(
        "---\ncefr_estimate: A2\n---\n# Alex\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "AUDIO_ROOT", tmp_path / ".audio")
    for name in ("AI_BASE_URL", "AI_MODEL", "AI_VISION_MODEL", "STT_BASE_URL", "STT_MODEL"):
        monkeypatch.setattr(config, name, "")
    monkeypatch.setattr(config, "TTS_BASE_URL", "")
    monkeypatch.setattr(config, "TTS_MODEL", "")
    monkeypatch.setattr(stt, "_word_timestamps", None)
    monkeypatch.setattr(status, "_last_probe", {})

    async def no_probe() -> None:
        return None

    # The startup probe would try the network; the tests set probe results by hand.
    monkeypatch.setattr(status, "safe_probe", no_probe)
    with TestClient(app_module.app) as c:
        yield c


def _chat_on(monkeypatch):
    monkeypatch.setattr(config, "AI_BASE_URL", "http://chat.test/v1")
    monkeypatch.setattr(config, "AI_MODEL", "chat-model")

    async def fake_chat(messages, temperature=None, max_tokens=None, **kw):
        return REPLY

    async def fake_stream(messages, temperature=None, max_tokens=None, **kw):
        for part in (REPLY[:20], REPLY[20:]):
            yield part

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_stream", fake_stream)


def _start(client, mode=1, **extra):
    r = client.post(
        "/session/start",
        json={"user_id": "alex", "target_language": "de", "mode": mode, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_health_without_chat_requires_setup(client):
    body = client.get("/health").json()
    assert body["status"] == "setup_required"
    chat = body["services"]["chat"]
    assert chat["configured"] is False
    assert "AI_BASE_URL" in chat["detail"]
    assert body["services"]["stt"]["configured"] is False
    assert body["services"]["tts"]["languages"] == []


def test_health_reports_an_unreachable_service_as_degraded(client, monkeypatch):
    _chat_on(monkeypatch)

    async def failing_probe() -> None:
        status._last_probe.clear()
        status._last_probe["chat"] = (False, "Cannot reach the chat server.")

    monkeypatch.setattr(status, "probe", failing_probe)
    body = client.get("/health?deep=1").json()
    assert body["status"] == "degraded"
    assert body["services"]["chat"]["reachable"] is False
    assert body["services"]["chat"]["detail"] == "Cannot reach the chat server."


def test_turn_without_chat_is_a_clear_503(client):
    sid = _start(client)
    r = client.post("/turn", data={"session_id": sid, "text": "Hallo"})
    assert r.status_code == 503
    body = r.json()
    assert body["service"] == "chat" and body["code"] == "not_configured"
    assert "AI_MODEL" in body["detail"]


def test_streamed_turn_without_chat_sends_an_error_event(client):
    sid = _start(client)
    r = client.post("/turn/stream", data={"session_id": sid, "text": "Hallo"})
    assert r.status_code == 200
    events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["code"] == "not_configured"
    assert not [e for e in events if e["type"] == "meta"]


def test_text_turn_works_without_speech_services(client, monkeypatch):
    _chat_on(monkeypatch)
    sid = _start(client)
    r = client.post("/turn", data={"session_id": sid, "text": "Hallo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Hallo Alex!"
    # No TTS configured: no audio and no warning, the browser speaks instead.
    assert body["audio_url"] is None


def test_streamed_turn_without_tts_still_sends_the_sentences(client, monkeypatch):
    _chat_on(monkeypatch)
    sid = _start(client)
    r = client.post("/turn/stream", data={"session_id": sid, "text": "Hallo"})
    events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    audio = [e for e in events if e["type"] == "audio"]
    assert audio and all(e["url"] is None for e in audio)
    assert "".join(e["text"] for e in audio).strip() == "Hallo Alex!"
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["warnings"] == []


def test_voice_turn_without_stt_is_a_clear_503(client, monkeypatch):
    _chat_on(monkeypatch)
    sid = _start(client)
    r = client.post(
        "/turn", data={"session_id": sid}, files={"audio": ("turn.webm", b"xx", "audio/webm")}
    )
    assert r.status_code == 503
    assert r.json()["service"] == "speech-to-text"


def test_pronunciation_without_word_timestamps_is_501(client, monkeypatch):
    _chat_on(monkeypatch)
    monkeypatch.setattr(config, "STT_BASE_URL", "http://stt.test/v1")
    monkeypatch.setattr(config, "STT_MODEL", "stt-model")

    async def no_words(*a, **kw):
        raise AIServiceError("speech-to-text", "unsupported", "No word timestamps.")

    monkeypatch.setattr(stt, "transcribe_words", no_words)
    sid = _start(client, mode=4, context="Guten Tag, ich heiße Alex.")
    r = client.post(
        "/read/score",
        data={"session_id": sid},
        files={"audio": ("read.webm", b"xx", "audio/webm")},
    )
    assert r.status_code == 501
    assert r.json()["code"] == "unsupported"


def test_page_photo_without_vision_model_is_503(client):
    r = client.post(
        "/ocr",
        data={"user_id": "alex", "target_language": "de"},
        files={"image": ("page.jpg", b"xx", "image/jpeg")},
    )
    assert r.status_code == 503
    assert r.json()["service"] == "vision"


def test_voices_are_empty_without_tts(client):
    body = client.get("/voices").json()
    assert body["voices"]["de"] == []
    assert {lang["code"] for lang in body["languages"]} == {"de", "en", "fr"}


def test_tts_failure_never_breaks_a_turn(client, monkeypatch):
    _chat_on(monkeypatch)
    monkeypatch.setattr(config, "TTS_BASE_URL", "http://tts.test/v1")
    monkeypatch.setattr(config, "TTS_MODEL", "tts-model")
    monkeypatch.setitem(config.LANGUAGES["de"], "voices", ["voice-a"])

    async def broken(*a, **kw):
        raise AIServiceError("text-to-speech", "unreachable", "Cannot reach the TTS server.")

    monkeypatch.setattr(tts, "synthesize", broken)
    sid = _start(client)
    r = client.post("/turn", data={"session_id": sid, "text": "Hallo"})
    assert r.status_code == 200
    assert r.json()["audio_url"] is None


def test_session_end_survives_a_failing_analyst(client, monkeypatch):
    _chat_on(monkeypatch)
    sid = _start(client)
    assert client.post("/turn", data={"session_id": sid, "text": "Hallo"}).status_code == 200

    async def slow(*a, **kw):
        raise AIServiceError("chat", "timeout", "The chat server took too long to answer.")

    monkeypatch.setattr(llm, "chat", slow)
    r = client.post("/session/end", json={"session_id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["turns"] == 1
    assert "took too long" in body["analysis_error"]
    # The turn itself was saved before the analysis failed.
    sessions = list((config.DATA_DIR / "alex" / "de" / "sessions").glob("*.md"))
    assert sessions and "Hallo" in sessions[0].read_text(encoding="utf-8")


def test_unreadable_recording_is_a_422_not_a_service_error(client, monkeypatch):
    _chat_on(monkeypatch)
    monkeypatch.setattr(config, "STT_BASE_URL", "http://stt.test/v1")
    monkeypatch.setattr(config, "STT_MODEL", "stt-model")
    sid = _start(client)
    r = client.post(
        "/turn", data={"session_id": sid}, files={"audio": ("turn.webm", b"xx", "audio/webm")}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "bad_audio"
