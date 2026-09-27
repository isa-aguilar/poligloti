"""Tests for minimal pairs: seed loader, verdict and tally."""

from __future__ import annotations

import pytest

from backend import config, memory, minimal_pairs


def test_load_pairs_de():
    groups = minimal_pairs.load_pairs("de")
    assert len(groups) >= 8
    g = next(g for g in groups if g["contrast"] == "iː/ɪ")
    assert g["tip"] and len(g["pairs"]) >= 2
    assert g["pairs"][0]["words"] == ["Miete", "Mitte"]
    assert "rent" in g["pairs"][0]["gloss"]


def test_pick_pairs_biased_by_misses(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    d = memory.user_lang_dir("alex", "de")
    (d / "phonemes.md").write_text(
        "# Phonemes and contrasts being tracked\n\n## Contrasts (minimal pairs)\n"
        "- yː/ʏ (Hüte-Hütte): 3 attempts · 0 distinguished · last 2026-07-01\n",
        encoding="utf-8",
    )
    picked = minimal_pairs.pick_pairs("alex", "de", n=8)
    assert len(picked) == 8
    # The contrast with previous misses is always selected.
    assert any(p["contrast"] == "yː/ʏ" for p in picked)
    # No duplicate pairs.
    keys = [tuple(p["words"]) for p in picked]
    assert len(keys) == len(set(keys))


def test_verdict():
    # Told both apart, in order.
    v = minimal_pairs.verdict(["Ofen", "offen"], ["ofen", "offen"])
    assert v["status"] == "ok"
    # Said the same word twice: the difference was not heard.
    v = minimal_pairs.verdict(["Ofen", "offen"], ["offen", "offen"])
    assert v["status"] == "same" and v["heard_as"] == "offen"
    # Noise / unrecognizable.
    v = minimal_pairs.verdict(["Ofen", "offen"], ["hallo"])
    assert v["status"] == "unclear"
    # Tolerates extra words around it (fillers).
    v = minimal_pairs.verdict(["Ofen", "offen"], ["also", "ofen", "offen", "ja"])
    assert v["status"] == "ok"


def test_contrast_tally(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    minimal_pairs.record_attempt("alex", "de", "yː/ʏ", "Hüte-Hütte", distinguished=False)
    minimal_pairs.record_attempt("alex", "de", "yː/ʏ", "Hüte-Hütte", distinguished=True)
    text = (memory.user_lang_dir("alex", "de") / "phonemes.md").read_text(encoding="utf-8")
    assert "yː/ʏ (Hüte-Hütte): 2 attempts · 1 distinguished" in text


@pytest.fixture()
def pairs_client(monkeypatch, tmp_path, make_learner):
    """App client with the AI services mocked (offline). `heard` sets what the
    fake speech-to-text returns."""
    from fastapi.testclient import TestClient

    from backend.services import llm, stt, tts
    from backend.sessions import SESSIONS

    data_dir = tmp_path / "data"
    audio_root = tmp_path / "audio"
    audio_root.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "AUDIO_ROOT", audio_root)
    make_learner(data_dir, languages=("de",))

    heard: list[str] = []

    async def fake_transcribe_words(
        audio, language, filename="p.wav", content_type=None, prompt=None
    ):
        assert prompt is None, "minimal pairs are transcribed WITHOUT a prompt"
        return " ".join(heard), [{"word": w} for w in heard]

    async def fake_synthesize(text, language, voice=None, length_scale=None):
        return b"RIFF\x00\x00\x00\x00WAVEfake"

    async def fake_warmup(system_prompt=None, user=None):
        return None

    monkeypatch.setattr(stt, "transcribe_words", fake_transcribe_words)
    monkeypatch.setattr(tts, "synthesize", fake_synthesize)
    monkeypatch.setattr(llm, "warmup", fake_warmup)

    from backend.app import app

    SESSIONS.clear()
    with TestClient(app) as c:
        c.heard = heard
        c.audio_root = audio_root
        yield c
    SESSIONS.clear()


def _start_pairs(client):
    res = client.post(
        "/session/start",
        json={"user_id": "alex", "target_language": "de", "mode": 4, "pair_mode": True},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_pairs_session_end_to_end(pairs_client, monkeypatch):
    """Integration: /session/start pair_mode pre-synthesizes and returns pairs
    with audio; /pairs/score scores them and updates the tally."""
    from backend.services import tts

    monkeypatch.setattr(tts, "configured", lambda language=None: True)
    data = _start_pairs(pairs_client)
    pairs = data["pairs"]
    assert len(pairs) == 8
    sid = data["session_id"]
    # Every pair carries pre-synthesized audio and the urls point to the session.
    assert all(u and u.startswith(f"/audio/{sid}/") for p in pairs for u in p["audio_urls"])
    # The WAV exists on disk under the forced session_id.
    assert (pairs_client.audio_root / sid / "000-01.wav").is_file()

    # Score the first pair by saying the two different words -> ok.
    pairs_client.heard[:] = pairs[0]["words"]
    score = pairs_client.post(
        "/pairs/score",
        data={"session_id": sid, "pair_index": 0},
        files={"audio": ("p.wav", b"RIFF", "audio/wav")},
    )
    assert score.status_code == 200, score.text
    assert score.json()["status"] == "ok"

    # The tally was written to phonemes.md for that pair's contrast.
    phonemes = (memory.user_lang_dir("alex", "de") / "phonemes.md").read_text(encoding="utf-8")
    assert "## Contrasts (minimal pairs)" in phonemes
    assert "1 attempts · 1 distinguished" in phonemes


def test_pairs_session_without_tts_has_no_audio(pairs_client, monkeypatch):
    """Without TTS for the language, synthesis is skipped silently: the pairs
    come without audio urls (the browser speaks instead) and nothing breaks."""
    from backend.services import tts

    async def must_not_synthesize(*a, **k):
        raise AssertionError("TTS called without being configured")

    monkeypatch.setattr(tts, "configured", lambda language=None: False)
    monkeypatch.setattr(tts, "synthesize", must_not_synthesize)
    data = _start_pairs(pairs_client)
    assert len(data["pairs"]) == 8
    assert all(u is None for p in data["pairs"] for u in p["audio_urls"])
