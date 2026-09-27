"""Contract of the AI clients against OpenAI-shaped responses. No network: every
request goes to an httpx.MockTransport that records it."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend import config, ocr
from backend.services import AIServiceError, llm, stt, tts

_RealClient = httpx.AsyncClient
# A fake recording above the minimum size; the fake servers never decode it.
_AUDIO = b"\x1a\x45\xdf\xa3" + b"\0" * 2000


@pytest.fixture
def ai(monkeypatch):
    """Configure all three services and route their HTTP to a handler."""
    monkeypatch.setattr(config, "AI_BASE_URL", "http://chat.test/v1")
    monkeypatch.setattr(config, "AI_API_KEY", "secret")
    monkeypatch.setattr(config, "AI_MODEL", "chat-model")
    monkeypatch.setattr(config, "AI_VISION_MODEL", "vision-model")
    monkeypatch.setattr(config, "AI_JSON_MODE", "auto")
    monkeypatch.setattr(config, "AI_SEND_USER", False)
    monkeypatch.setattr(config, "STT_BASE_URL", "http://stt.test/v1")
    monkeypatch.setattr(config, "STT_API_KEY", "")
    monkeypatch.setattr(config, "STT_MODEL", "stt-model")
    monkeypatch.setattr(config, "TTS_BASE_URL", "http://tts.test/v1")
    monkeypatch.setattr(config, "TTS_API_KEY", "")
    monkeypatch.setattr(config, "TTS_MODEL", "tts-model")
    monkeypatch.setitem(config.LANGUAGES["de"], "voices", ["voice-a", "voice-b"])
    monkeypatch.setattr(llm, "_json_mode_supported", True)
    monkeypatch.setattr(stt, "_word_timestamps", None)
    # Never transcode in tests: the fake servers accept anything.
    monkeypatch.setattr(stt, "_FFMPEG", None)

    state: dict = {"requests": [], "handler": None}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    transport = httpx.MockTransport(transport_handler)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: _RealClient(*a, transport=transport, **kw)
    )
    return state


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
    )


def _run(coro):
    return asyncio.run(coro)


# --- chat ---------------------------------------------------------------------


def test_chat_sends_openai_request_with_key(ai):
    ai["handler"] = lambda r: _completion("Hallo!")
    assert _run(llm.chat([{"role": "user", "content": "hi"}])) == "Hallo!"
    req = ai["requests"][0]
    assert str(req.url) == "http://chat.test/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer secret"
    body = json.loads(req.content)
    assert body["model"] == "chat-model"
    assert "response_format" not in body  # free text asks for no format
    assert "user" not in body


def test_json_output_asks_for_json_object(ai):
    ai["handler"] = lambda r: _completion("{}")
    _run(llm.chat([{"role": "user", "content": "JSON please"}], output="json"))
    body = json.loads(ai["requests"][0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_auto_json_mode_falls_back_when_the_server_rejects_it(ai):
    def handler(request: httpx.Request) -> httpx.Response:
        if "response_format" in json.loads(request.content):
            return httpx.Response(400, json={"error": "response_format is not supported"})
        return _completion('{"reply": "ok"}')

    ai["handler"] = handler
    out = _run(llm.chat([{"role": "user", "content": "x"}], output="teacher"))
    assert out == '{"reply": "ok"}'
    assert len(ai["requests"]) == 2
    # Later calls skip response_format directly.
    _run(llm.chat([{"role": "user", "content": "x"}], output="json"))
    assert "response_format" not in json.loads(ai["requests"][2].content)


def test_gbnf_mode_sends_the_teacher_grammar(ai, monkeypatch):
    monkeypatch.setattr(config, "AI_JSON_MODE", "gbnf")
    ai["handler"] = lambda r: _completion("{}")
    _run(llm.chat([{"role": "user", "content": "x"}], output="teacher"))
    body = json.loads(ai["requests"][0].content)
    assert body["grammar"].startswith("root ::=")
    assert "response_format" not in body


def test_off_mode_sends_no_format(ai, monkeypatch):
    monkeypatch.setattr(config, "AI_JSON_MODE", "off")
    ai["handler"] = lambda r: _completion("{}")
    _run(llm.chat([{"role": "user", "content": "x"}], output="teacher"))
    body = json.loads(ai["requests"][0].content)
    assert "response_format" not in body and "grammar" not in body


def test_user_field_only_when_enabled(ai, monkeypatch):
    ai["handler"] = lambda r: _completion("ok")
    _run(llm.chat([{"role": "user", "content": "x"}], user="alex"))
    assert "user" not in json.loads(ai["requests"][0].content)
    monkeypatch.setattr(config, "AI_SEND_USER", True)
    _run(llm.chat([{"role": "user", "content": "x"}], user="alex"))
    assert json.loads(ai["requests"][1].content)["user"] == "alex"


def test_chat_stream_yields_deltas(ai):
    events = [
        {"choices": [{"delta": {"content": "Hal"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}},
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    ai["handler"] = lambda r: httpx.Response(
        200, text=sse, headers={"content-type": "text/event-stream"}
    )

    async def collect():
        return [d async for d in llm.chat_stream([{"role": "user", "content": "x"}])]

    assert _run(collect()) == ["Hal", "lo"]
    body = json.loads(ai["requests"][0].content)
    assert body["stream"] is True


def test_chat_errors_are_typed(ai):
    ai["handler"] = lambda r: httpx.Response(401, json={"error": "bad key"})
    with pytest.raises(AIServiceError) as err:
        _run(llm.chat([{"role": "user", "content": "x"}]))
    assert err.value.service == "chat" and err.value.code == "unauthorized"

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    ai["handler"] = refuse
    with pytest.raises(AIServiceError) as err:
        _run(llm.chat([{"role": "user", "content": "x"}]))
    assert err.value.code == "unreachable"


def test_chat_without_configuration_says_what_is_missing(ai, monkeypatch):
    monkeypatch.setattr(config, "AI_MODEL", "")
    with pytest.raises(AIServiceError) as err:
        _run(llm.chat([{"role": "user", "content": "x"}]))
    assert err.value.code == "not_configured"
    assert "AI_MODEL" in err.value.message
    assert ai["requests"] == []


# --- vision -------------------------------------------------------------------


def test_ocr_sends_a_data_url_to_the_vision_model(ai):
    ai["handler"] = lambda r: _completion("Erste Zeile\n\n12\n\nzweiter Ab-\nsatz")
    text = _run(ocr.transcribe_page(b"\x89PNG fake", "image/png", "de"))
    body = json.loads(ai["requests"][0].content)
    assert body["model"] == "vision-model"
    part = body["messages"][0]["content"][1]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    assert "12" not in text  # page numbers are cleaned up


def test_ocr_without_vision_model_is_not_configured(ai, monkeypatch):
    monkeypatch.setattr(config, "AI_VISION_MODEL", "")
    with pytest.raises(AIServiceError) as err:
        _run(ocr.transcribe_page(b"x", "image/png", "de"))
    assert err.value.code == "not_configured"


# --- speech-to-text -----------------------------------------------------------


def test_transcribe_posts_multipart_with_language_and_prompt(ai):
    ai["handler"] = lambda r: httpx.Response(200, json={"text": " Guten Tag "})
    text = _run(stt.transcribe(_AUDIO, "de", prompt="Alex"))
    assert text == "Guten Tag"
    req = ai["requests"][0]
    assert str(req.url) == "http://stt.test/v1/audio/transcriptions"
    assert "authorization" not in req.headers  # no key configured for this server
    raw = req.content.decode(errors="replace")
    for field in ('name="model"', "stt-model", 'name="language"', 'name="prompt"'):
        assert field in raw


def test_words_openai_shape(ai):
    payload = {
        "text": "Guten Tag",
        "words": [
            {"word": "Guten", "start": 0, "end": 0.4},
            {"word": "Tag", "start": 0.4, "end": 0.8},
        ],
    }
    ai["handler"] = lambda r: httpx.Response(200, json=payload)
    _, words = _run(stt.transcribe_words(_AUDIO, "de"))
    assert [w["word"] for w in words] == ["Guten", "Tag"]
    assert words[0]["probability"] is None
    assert stt.word_timestamps_supported() is True


def test_words_whisper_cpp_shape_merges_subtokens(ai):
    payload = {
        "text": "Die Logistik",
        "segments": [
            {
                "words": [
                    {"word": " Die", "probability": 0.9},
                    {"word": " Log", "probability": 0.8},
                    {"word": "ist", "probability": 0.4},
                    {"word": "ik", "probability": 0.7},
                ]
            }
        ],
    }
    ai["handler"] = lambda r: httpx.Response(200, json=payload)
    _, words = _run(stt.transcribe_words(_AUDIO, "de"))
    assert [w["word"] for w in words] == ["Die", "Logistik"]
    assert words[1]["probability"] == 0.4


def test_server_without_word_timestamps_disables_the_feature(ai):
    ai["handler"] = lambda r: httpx.Response(200, json={"text": "Guten Tag"})
    with pytest.raises(AIServiceError) as err:
        _run(stt.transcribe_words(_AUDIO, "de"))
    assert err.value.code == "unsupported"
    assert stt.word_timestamps_supported() is False
    # The next attempt fails fast, without calling the server again.
    with pytest.raises(AIServiceError):
        _run(stt.transcribe_words(_AUDIO, "de"))
    assert len(ai["requests"]) == 1


# --- text-to-speech -----------------------------------------------------------


def test_synthesize_uses_openai_speech_fields(ai):
    ai["handler"] = lambda r: httpx.Response(200, content=b"RIFF....WAVE")
    audio = _run(tts.synthesize("Hallo", "de", voice="voice-b", length_scale=1.25))
    assert audio == b"RIFF....WAVE"
    req = ai["requests"][0]
    assert str(req.url) == "http://tts.test/v1/audio/speech"
    body = json.loads(req.content)
    assert body == {
        "model": "tts-model",
        "input": "Hallo",
        "voice": "voice-b",
        "response_format": "wav",
        "speed": 0.8,
    }


def test_unknown_voice_falls_back_to_the_language_default(ai):
    ai["handler"] = lambda r: httpx.Response(200, content=b"wav")
    _run(tts.synthesize("Hallo", "de", voice="not-configured"))
    assert json.loads(ai["requests"][0].content)["voice"] == "voice-a"


def test_tts_is_per_language(ai):
    assert tts.configured("de") is True
    assert tts.configured("fr") is False
    with pytest.raises(AIServiceError) as err:
        _run(tts.synthesize("Bonjour", "fr"))
    assert err.value.code == "not_configured"


def test_a_language_can_use_its_own_tts_model(ai, monkeypatch):
    # With speaches every Piper voice is its own model.
    monkeypatch.setitem(config.LANGUAGES["fr"], "voices", ["siwis"])
    monkeypatch.setitem(config.LANGUAGES["fr"], "tts_model", "piper-fr_FR-siwis-medium")
    ai["handler"] = lambda r: httpx.Response(200, content=b"wav")
    _run(tts.synthesize("Bonjour", "fr"))
    _run(tts.synthesize("Hallo", "de"))
    models = [json.loads(r.content)["model"] for r in ai["requests"]]
    assert models == ["piper-fr_FR-siwis-medium", "tts-model"]


def test_an_empty_recording_gets_a_clear_message(ai):
    ai["handler"] = lambda r: httpx.Response(200, json={"text": "never called"})
    with pytest.raises(AIServiceError) as err:
        _run(stt.transcribe(b"\x1a\x45\xdf\xa3", "de"))
    assert err.value.code == "bad_audio"
    assert "Try again" in err.value.message
    assert ai["requests"] == []


def test_undecodable_recording_hides_the_ffmpeg_details(ai, monkeypatch):
    if not stt.shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    monkeypatch.setattr(stt, "_FFMPEG", stt.shutil.which("ffmpeg"))
    with pytest.raises(AIServiceError) as err:
        _run(stt.transcribe(_AUDIO, "de"))
    assert err.value.code == "bad_audio"
    assert "EBML" not in err.value.message and "pipe" not in err.value.message
