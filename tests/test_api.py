"""Endpoint smoke tests with TestClient and mocked services.

Offline: chat/STT/TTS are monkeypatched (if something tried the network the
test would fail, which is what we want). Data and audio go to tmp_path.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import config, memory
from backend.services import llm, status, stt, tts
from backend.sessions import SESSIONS

CONTRACT = {
    "reply": "Hallo Alex! Wie geht es dir heute? Lass uns ein bisschen sprechen und üben.",
    "corrections": [
        {"original": "Ich habe gegangen", "corrected": "Ich bin gegangen", "note": "sein + motion"}
    ],
    "new_vocab": [
        {
            "term": "die Bordkarte",
            "translation": "boarding pass",
            "example": "Hier ist meine Bordkarte.",
        }
    ],
    "suggested_followup": "Was hast du heute gemacht?",
}

_RealAsyncClient = httpx.AsyncClient


@pytest.fixture()
def client(monkeypatch, tmp_path, make_learner):
    # Data roots in tmp: never touch the real data/ or .runtime/.
    data_dir = tmp_path / "data"
    audio_root = tmp_path / "audio"
    audio_root.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "AUDIO_ROOT", audio_root)
    make_learner(data_dir, languages=("de",))
    # This week's review already done: the mode 1 weekly push does not fire
    # (the tests would be non-deterministic on Mondays).
    review_dir = data_dir / "alex" / "de" / "weekly-reviews"
    review_dir.mkdir()
    (review_dir / f"{memory.iso_week_label()}.md").write_text("ok\n", encoding="utf-8")

    # No startup probe (it would race with the health tests) and no stale
    # probe result left over from another test.
    async def no_probe():
        return None

    monkeypatch.setattr(status, "safe_probe", no_probe)
    monkeypatch.setattr(status, "_last_probe", {})

    # Mocked services: no network calls.
    async def fake_chat(messages, temperature=None, max_tokens=None, **kwargs):
        return json.dumps(CONTRACT, ensure_ascii=False)

    async def fake_chat_stream(messages, temperature=None, max_tokens=None, **kwargs):
        raw = json.dumps(CONTRACT, ensure_ascii=False)
        # Arbitrary delta sizes, like the real SSE.
        for i in range(0, len(raw), 7):
            yield raw[i : i + 7]

    async def fake_warmup(system_prompt=None, **kwargs):
        return None

    async def fake_transcribe(audio, language, filename="turn.wav", content_type=None, prompt=None):
        return "hallo"

    async def fake_synthesize(text, language, voice=None, length_scale=None):
        return b"RIFF\x00\x00\x00\x00WAVEfake-bytes"

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(llm, "warmup", fake_warmup)
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(tts, "synthesize", fake_synthesize)

    from backend.app import app

    SESSIONS.clear()
    with TestClient(app) as c:
        yield c
    SESSIONS.clear()


@pytest.fixture()
def tts_on(monkeypatch):
    """TTS configured for every language (synthesis itself stays mocked)."""
    monkeypatch.setattr(tts, "configured", lambda language=None: True)


def _start(client, **overrides) -> dict:
    body = {"user_id": "alex", "target_language": "de", "mode": 1, **overrides}
    resp = client.post("/session/start", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _sse_events(resp) -> list[dict]:
    events = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
def test_health_without_ai_is_setup_required(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "setup_required"
    assert data["version"]
    assert data["active_sessions"] == 0
    services = data["services"]
    assert services["chat"]["configured"] is False
    assert services["chat"]["detail"]
    assert services["chat"]["vision"] is False
    assert services["stt"]["configured"] is False
    assert services["stt"]["word_timestamps"] is False
    assert services["tts"]["configured"] is False
    assert services["tts"]["languages"] == []


@pytest.fixture()
def chat_configured(monkeypatch):
    monkeypatch.setattr(config, "AI_BASE_URL", "http://ai.test/v1")
    monkeypatch.setattr(config, "AI_MODEL", "test-model")


def _mock_network(monkeypatch, route):
    """Route every httpx.AsyncClient request to `route(request) -> httpx.Response`.
    Returns the list of requests seen."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return route(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )
    return seen


def _all_good(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/chat/completions"):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    return httpx.Response(200, json={"data": []})


def test_health_with_chat_only_is_ok(client, chat_configured, monkeypatch):
    """Leaving speech-to-text and text-to-speech unset is a valid choice, not a fault."""
    _mock_network(monkeypatch, _all_good)
    data = client.get("/health?deep=1").json()
    chat = data["services"]["chat"]
    assert chat["configured"] is True and chat["reachable"] is True
    assert not chat.get("detail")
    assert chat["vision"] is False
    assert data["services"]["stt"]["configured"] is False
    assert data["status"] == "ok"


def test_health_deep_chat_and_tts_ok(client, chat_configured, monkeypatch):
    monkeypatch.setattr(config, "TTS_BASE_URL", "http://tts.test/v1")
    monkeypatch.setattr(config, "TTS_MODEL", "tts-model")
    monkeypatch.setitem(config.LANGUAGES, "de", {"name": "German", "voices": ["voice-a"]})
    _mock_network(monkeypatch, _all_good)
    data = client.get("/health?deep=1").json()
    assert data["services"]["chat"]["reachable"] is True
    assert data["services"]["tts"]["configured"] is True
    assert data["services"]["tts"]["reachable"] is True
    assert data["services"]["tts"]["languages"] == ["de"]
    assert data["status"] == "ok"


def test_health_deep_chat_unreachable(client, chat_configured, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    _mock_network(monkeypatch, refuse)
    data = client.get("/health?deep=1").json()
    assert data["services"]["chat"]["reachable"] is False
    assert "cannot reach" in data["services"]["chat"]["detail"].lower()
    assert data["status"] == "degraded"


# The health check has to call the model for real. A server can keep listing a
# model whose worker process died: the list answers 200 while every turn
# fails. A list of models does not prove that the model answers.


def test_health_deep_detects_a_listed_model_that_does_not_answer(
    client, chat_configured, monkeypatch
):
    def worker_dead(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(500, json={"error": {"message": "cannot connect to worker"}})
        return httpx.Response(200)

    _mock_network(monkeypatch, worker_dead)
    data = client.get("/health?deep=1").json()

    chat = data["services"]["chat"]
    assert chat["reachable"] is False, "listing the model does not prove it answers"
    assert data["status"] == "degraded"
    assert "model" in chat["detail"].lower()


def test_health_deep_chat_ok_needs_a_real_answer(client, chat_configured, monkeypatch):
    def empty_choices(request):
        return httpx.Response(200, json={"choices": []})

    _mock_network(monkeypatch, empty_choices)
    data = client.get("/health?deep=1").json()
    assert data["services"]["chat"]["reachable"] is False
    assert "empty" in data["services"]["chat"]["detail"].lower()

    _mock_network(monkeypatch, _all_good)
    data = client.get("/health?deep=1").json()
    assert data["services"]["chat"]["reachable"] is True
    assert not data["services"]["chat"].get("detail")
    assert data["status"] == "ok"


def test_health_completion_is_minimal_and_uses_the_configured_model(
    client, chat_configured, monkeypatch
):
    seen = _mock_network(monkeypatch, _all_good)
    client.get("/health?deep=1")

    completions = [r for r in seen if r.url.path.endswith("/chat/completions")]
    assert len(completions) == 1, "a single call per check"
    body = json.loads(completions[0].content)
    assert body["model"] == config.AI_MODEL
    assert body["max_tokens"] <= 4, "the health check must not generate text"


def test_cheap_health_never_calls_the_model(client, chat_configured, monkeypatch):
    seen = _mock_network(monkeypatch, _all_good)
    data = client.get("/health").json()

    assert seen == [], "without deep the network is not touched"
    # No probe has run yet: configured, reachability unknown.
    assert data["services"]["chat"]["configured"] is True
    assert data["services"]["chat"].get("reachable") is None


def test_health_distinguishes_a_slow_model_from_a_dead_service(
    client, chat_configured, monkeypatch
):
    """A timeout is not the same as a dead service: the model may be loading."""

    def slow(request):
        raise httpx.ReadTimeout("timeout", request=request)

    _mock_network(monkeypatch, slow)
    data = client.get("/health?deep=1").json()

    chat = data["services"]["chat"]
    assert chat["reachable"] is False
    detail = chat["detail"].lower()
    assert "slow" in detail or "loading" in detail, detail
    assert "cannot reach" not in detail


def test_health_reports_a_rejected_api_key(client, chat_configured, monkeypatch):
    _mock_network(monkeypatch, lambda request: httpx.Response(401))
    chat = client.get("/health?deep=1").json()["services"]["chat"]
    assert chat["reachable"] is False
    assert "api key" in chat["detail"].lower()


# ---------------------------------------------------------------------------
# /profiles, /voices
# ---------------------------------------------------------------------------
def test_profiles_lists_alex(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert [p["user"] for p in profiles] == ["alex"]
    assert profiles[0]["name"] == "Alex"
    assert profiles[0]["primary_language"] == "de"
    assert profiles[0]["languages_studied"] == ["de"]
    assert profiles[0]["ui_language"] == "en"


def test_profiles_expose_started_languages(client):
    """languages_started = the ones with a data folder, not the declared ones."""
    profiles = client.get("/profiles").json()["profiles"]
    assert profiles[0]["languages_started"] == ["de"]
    # Starting a language that is NOT in languages_studied makes it show up here.
    (config.DATA_DIR / "alex" / "en").mkdir(parents=True, exist_ok=True)
    profiles = client.get("/profiles").json()["profiles"]
    assert profiles[0]["languages_started"] == ["de", "en"]
    assert profiles[0]["languages_studied"] == ["de"]  # the declared list does not change


def test_voices_expose_the_language_catalogue(client):
    """The picker offers ALL supported languages, not only the studied ones."""
    body = client.get("/voices").json()
    assert set(body) == {"voices", "languages", "rates"}
    codes = [lang["code"] for lang in body["languages"]]
    assert codes == list(config.SUPPORTED_LANGS)
    assert all(lang["name"] for lang in body["languages"])
    # The catalogue and the voices must cover the same languages: adding a
    # language without voices (or the other way round) is caught here.
    assert set(codes) == set(body["voices"])
    assert set(body["rates"]) == {"slow", "normal", "fast"}


def test_voices_list_the_configured_voices(client, monkeypatch):
    monkeypatch.setitem(config.LANGUAGES, "de", {"name": "German", "voices": ["v1", "v2"]})
    body = client.get("/voices").json()
    assert body["voices"]["de"] == [{"id": "v1", "label": "v1"}, {"id": "v2", "label": "v2"}]


# ---------------------------------------------------------------------------
# Sessions and turns
# ---------------------------------------------------------------------------
def test_start_undeclared_language(client):
    """Any learner can start any supported language."""
    resp = client.post(
        "/session/start",
        json={"user_id": "alex", "target_language": "en", "mode": 1},
    )
    assert resp.status_code == 200, resp.text
    assert (config.DATA_DIR / "alex" / "en").is_dir()


def test_session_start_mode1(client):
    data = _start(client)
    assert data["session_id"]
    assert data["mode"] == 1
    assert data["opening"] is None
    assert data["opening_pending"] is False
    assert data["weekly_review"] is False


def test_text_turn(client):
    sid = _start(client)["session_id"]
    # The text includes the sentence the CONTRACT corrects: a correction quoting
    # something the learner did not say is dropped
    # (llm_parse.drop_stale_corrections).
    said = "Hallo, wie geht's? Gestern ich habe gegangen nach Hause."
    resp = client.post("/turn", data={"session_id": sid, "text": said})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["session_id"] == sid
    assert data["turn"] == 1
    assert data["transcript"] == said
    assert data["reply"] == CONTRACT["reply"]
    assert data["corrections"][0]["corrected"] == "Ich bin gegangen"
    assert data["new_vocab"][0]["term"] == "die Bordkarte"
    # Without TTS configured there is no audio and no warning: the browser speaks.
    assert data["audio_url"] is None
    assert not data.get("warnings")


def test_text_turn_with_tts(client, tts_on):
    sid = _start(client)["session_id"]
    resp = client.post("/turn", data={"session_id": sid, "text": "Hallo!"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["audio_url"] == f"/audio/{sid}/001.wav"
    assert (config.AUDIO_ROOT / sid / "001.wav").is_file()


def test_session_start_mode2_defer_opening(client):
    data = _start(client, mode=2, scenario="everyday/supermarket", defer_opening=True)
    assert data["opening_pending"] is True
    assert data["opening"] is None
    assert data["scenario_info"] is not None
    # The session exists with no turns: ready for the streamed kickoff.
    assert SESSIONS[data["session_id"]]["turns"] == 0


def test_session_start_mode2_unknown_scenario(client):
    resp = client.post(
        "/session/start",
        json={"user_id": "alex", "target_language": "de", "mode": 2, "scenario": "work/nope"},
    )
    assert resp.status_code == 404


def test_turn_stream_kickoff(client):
    sid = _start(client, mode=2, scenario="everyday/supermarket", defer_opening=True)["session_id"]
    resp = client.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    assert resp.status_code == 200, resp.text
    events = _sse_events(resp)
    types = [e["type"] for e in events]
    assert "transcript" in types and "meta" in types and "done" in types
    transcript_evt = next(e for e in events if e["type"] == "transcript")
    assert transcript_evt["text"] == ""
    meta = next(e for e in events if e["type"] == "meta")
    assert meta["reply"] == CONTRACT["reply"]
    assert meta["turn"] == 1
    assert SESSIONS[sid]["turns"] == 1


def test_turn_stream_kickoff_only_on_first_turn(client):
    sid = _start(client, mode=2, scenario="everyday/supermarket", defer_opening=True)["session_id"]
    resp = client.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    assert resp.status_code == 200
    # With turns > 0 the kickoff is rejected.
    resp = client.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    assert resp.status_code == 400


def test_session_end_closes_and_purges(client, tts_on):
    sid = _start(client)["session_id"]
    client.post("/turn", data={"session_id": sid, "text": "Hallo!"})
    audio_dir = config.AUDIO_ROOT / sid
    assert audio_dir.is_dir()  # the turn left its WAV
    resp = client.post("/session/end", json={"session_id": sid})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["closed"] == sid
    assert data["turns"] == 1
    # The extra closing fields (mode 1) survive the response_model.
    assert "progress_updated" in data
    assert sid not in SESSIONS
    assert not audio_dir.exists()
    # Closing twice does not finalize twice.
    assert client.post("/session/end", json={"session_id": sid}).status_code == 404


def test_weekly_review_close_returns_the_flag(client):
    """The weekly review is persisted at the opening; the close only reports it."""
    sid = _start(client, mode=6, sub_mode="weekly_review", defer_opening=True)["session_id"]
    resp = client.post("/session/end", json={"session_id": sid})
    assert resp.status_code == 200, resp.text
    assert resp.json()["weekly_review"] is True


def test_invalid_mode6_sub_mode(client):
    resp = client.post(
        "/session/start",
        json={"user_id": "alex", "target_language": "de", "mode": 6, "sub_mode": "revision"},
    )
    assert resp.status_code == 400


def test_teacher_turn_asks_for_teacher_output(client, monkeypatch):
    """The teacher turn asks for the teacher contract (output="teacher"); the
    warmup and the analyst passes do not."""
    calls: list = []

    async def rec_chat(messages, temperature=None, max_tokens=None, **kwargs):
        calls.append(kwargs)
        return json.dumps(CONTRACT, ensure_ascii=False)

    monkeypatch.setattr(llm, "chat", rec_chat)
    sid = _start(client)["session_id"]
    resp = client.post("/turn", data={"session_id": sid, "text": "Hallo!"})
    assert resp.status_code == 200
    assert calls[-1]["output"] == "teacher"
    assert calls[-1]["user"] == "alex"
    assert "model" not in calls[-1] and "grammar" not in calls[-1]


def test_chat_not_configured_is_a_503(client, monkeypatch):
    """A missing AI service is a clear, typed error, never a 500."""
    from backend.services import AIServiceError

    async def not_configured(*a, **k):
        raise AIServiceError("chat", "not_configured", "No chat model configured.")

    monkeypatch.setattr(llm, "chat", not_configured)
    sid = _start(client)["session_id"]
    resp = client.post("/turn", data={"session_id": sid, "text": "Hallo!"})
    assert resp.status_code == 503
    assert resp.json() == {
        "detail": "No chat model configured.",
        "service": "chat",
        "code": "not_configured",
    }


def test_progress_without_data(client):
    resp = client.get("/progress/alex/de")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_data"] is False
    assert data["user"] == "alex" and data["lang"] == "de"
    assert len(data["dims"]) == 8
