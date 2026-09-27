"""Tests for the CEFR syllabus (backend/syllabus.py) and mode 9."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import config, syllabus

SEED = """# Test syllabus

## A1

### a1-01 · Greetings
- **Grammar**: sein and heißen.
- **Goal**: introduce yourself.
- **Key points**:
  - ich bin / ich heiße
- **Examples**:
  - Hallo, ich bin Alex. (Hi, I'm Alex.)
- **Suggested practice**: introduce yourself to a colleague.

### a1-02 · Articles
- **Grammar**: der/die/das.
- **Goal**: use gender correctly.
- **Key points**:
  - der Mann, die Frau, das Kind
- **Examples**:
  - Das ist der Plan. (That is the plan.)
- **Suggested practice**: describe objects in the office.

## A2

### a2-01 · Perfekt
- **Grammar**: haben/sein + Partizip II.
- **Goal**: talk about the past.
- **Key points**:
  - ich habe gearbeitet
- **Examples**:
  - Ich habe gestern gearbeitet. (I worked yesterday.)
- **Suggested practice**: tell how your day went yesterday.
"""


@pytest.fixture()
def mem(tmp_path, monkeypatch, make_learner):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    prompts = tmp_path / "prompts"
    (prompts / "syllabus").mkdir(parents=True)
    (prompts / "syllabus" / "de.md").write_text(SEED, encoding="utf-8")
    monkeypatch.setattr(config, "PROMPTS_ROOT", prompts)
    syllabus.load_syllabus.cache_clear()
    make_learner(data_dir, cefr="A1", languages=("de",))
    yield data_dir
    syllabus.load_syllabus.cache_clear()


def test_load_syllabus_parses_levels_and_topics(mem):
    data = syllabus.load_syllabus("de")
    assert list(data.keys()) == ["A1", "A2"]
    assert [t["id"] for t in data["A1"]] == ["a1-01", "a1-02"]
    t = data["A1"][0]
    assert t["title"] == "Greetings"
    assert "sein" in t["grammar"]
    assert t["goal"] == "introduce yourself."
    assert t["key_points"] == ["ich bin / ich heiße"]
    assert t["examples"] == ["Hallo, ich bin Alex. (Hi, I'm Alex.)"]
    assert "colleague" in t["practice"]


def test_topic_by_id_and_unknown(mem):
    assert syllabus.topic_by_id("de", "a2-01")["title"] == "Perfekt"
    assert syllabus.topic_by_id("de", "zz-99") is None


def test_default_status_is_pending_and_set(mem):
    assert syllabus.read_user_syllabus("alex", "de") == {}
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    st = syllabus.read_user_syllabus("alex", "de")
    assert st["a1-01"]["status"] == "seen"
    assert st["a1-01"]["date"]  # YYYY-MM-DD


def test_status_never_goes_back(mem):
    syllabus.set_topic_status("alex", "de", "a1-01", "practiced")
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    assert syllabus.read_user_syllabus("alex", "de")["a1-01"]["status"] == "practiced"


def test_invalid_status_is_ignored(mem):
    syllabus.set_topic_status("alex", "de", "a1-01", "perfect")
    assert syllabus.read_user_syllabus("alex", "de") == {}


def test_next_topic_order_and_levels(mem):
    # level A1, everything pending: the first one
    assert syllabus.next_topic("alex", "de")["id"] == "a1-01"
    # a1-01 mastered: next pending
    syllabus.set_topic_status("alex", "de", "a1-01", "mastered")
    assert syllabus.next_topic("alex", "de")["id"] == "a1-02"
    # no pending left: resume the seen one
    syllabus.set_topic_status("alex", "de", "a1-02", "seen")
    assert syllabus.next_topic("alex", "de")["id"] == "a1-02"
    # whole level mastered: jumps to A2 even though the CEFR is still A1
    syllabus.set_topic_status("alex", "de", "a1-02", "mastered")
    assert syllabus.next_topic("alex", "de")["id"] == "a2-01"


def test_next_topic_compound_cefr(mem):
    # "A2-B1" works on level A2
    user_md = config.DATA_DIR / "alex" / "de" / "USER.md"
    user_md.write_text("---\ncefr_estimate: A2-B1\n---\n\n# Alex\n", encoding="utf-8")
    assert syllabus.next_topic("alex", "de")["id"] == "a2-01"


def test_topic_session_count(mem):
    assert syllabus.topic_session_count("alex", "de", "a1-01") == 0
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    assert syllabus.topic_session_count("alex", "de", "a1-01") == 1


def test_overview(mem):
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    ov = syllabus.syllabus_overview("alex", "de")
    assert ov["levels"][0]["level"] == "A1"
    topics = ov["levels"][0]["topics"]
    assert topics[0] == {
        "id": "a1-01",
        "title": "Greetings",
        "status": "seen",
        "date": topics[0]["date"],
    }
    assert topics[1]["status"] == "pending"
    assert ov["next"] == {"id": "a1-02", "title": "Articles"}


def test_last_lesson_date(mem):
    assert syllabus.last_lesson_date("alex", "de") is None
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    assert syllabus.last_lesson_date("alex", "de") is not None


def test_memory_block_includes_topic_in_progress(mem):
    from backend import memory

    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    block = memory.build_memory_block("alex", "de")
    assert "### Syllabus topic in progress" in block
    assert "Greetings" in block


def test_suggestion_lesson_with_cooldown(mem, monkeypatch):
    from backend import memory, srs, suggestion, teacher

    # existing tracker + no review due + no SRS + no focus
    memory.write_skill_tracker("alex", "de", "A1", dict.fromkeys(config.SKILL_KEYS, 40), [], [])
    # Learner already assessed: otherwise the suggestion is the initial assessment.
    memory.write_assessment("alex", "de", "# Initial assessment\n")
    monkeypatch.setattr(teacher, "weekly_review_due", lambda u, lang: False)
    monkeypatch.setattr(
        srs,
        "due_payload",
        lambda u, lang, limit=None: {"due": [], "due_count": 0, "total_cards": 0},
    )
    # no lesson date yet: suggests a lesson
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] == "lesson" and s["mode"] == 9 and s["topic_id"] == "a1-01"
    # a lesson today: cooldown, falls through to the next rule
    syllabus.set_topic_status("alex", "de", "a1-01", "seen")
    s = suggestion.build_suggestion("alex", "de")
    assert s["kind"] != "lesson"


# ---------------------------------------------------------------------------
# `client` fixture: TestClient with mocked services and the REAL syllabus seed.
# Unlike `mem`, it does NOT monkeypatch PROMPTS_ROOT (the mode 9 prompts live in
# the real prompts/<lang>/ and the real seed has a1-01 = "Greetings and ...").
# ---------------------------------------------------------------------------
_CONTRACT = {
    "reply": "Hallo Alex! Heute üben wir die Begrüßung. Wie heißt du?",
    "corrections": [],
    "new_vocab": [],
    "suggested_followup": "Wie heißt du?",
}


@pytest.fixture()
def client(monkeypatch, tmp_path, make_learner):
    from backend import memory
    from backend.services import llm, stt, tts
    from backend.sessions import SESSIONS

    data_dir = tmp_path / "data"
    audio_root = tmp_path / "audio"
    audio_root.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "AUDIO_ROOT", audio_root)
    # Real seed: clear the cache in case a `mem` test cached a synthetic seed.
    syllabus.load_syllabus.cache_clear()
    make_learner(data_dir, cefr="A1", languages=("de",))
    # This week's review already done (avoids the non-deterministic weekly push).
    review_dir = data_dir / "alex" / "de" / "weekly-reviews"
    review_dir.mkdir()
    (review_dir / f"{memory.iso_week_label()}.md").write_text("ok\n", encoding="utf-8")

    calls: list[dict] = []

    async def fake_chat(messages, temperature=None, max_tokens=None, **kwargs):
        calls.append(kwargs)
        return json.dumps(_CONTRACT, ensure_ascii=False)

    async def fake_chat_stream(messages, temperature=None, max_tokens=None, **kwargs):
        raw = json.dumps(_CONTRACT, ensure_ascii=False)
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
        c.llm_calls = calls
        yield c
    SESSIONS.clear()
    syllabus.load_syllabus.cache_clear()


def _start_lesson(client, **extra):
    return client.post(
        "/session/start",
        json={
            "user_id": "alex",
            "target_language": "de",
            "mode": 9,
            "defer_opening": True,
            **extra,
        },
    )


def test_session_start_mode9_injects_topic_and_marks_seen(client):
    r = _start_lesson(client, topic_id="a1-01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["opening_pending"] is True
    sp = body["system_prompt"]
    assert "Greetings" in sp and "ich bin / ich heiße" in sp
    assert syllabus.read_user_syllabus("alex", "de")["a1-01"]["status"] == "seen"


def test_session_start_mode9_without_topic_uses_next(client):
    r = _start_lesson(client)
    assert r.status_code == 200, r.text
    assert "a1-01" in r.json()["system_prompt"]


def test_session_start_mode9_invalid_topic_400(client):
    r = _start_lesson(client, topic_id="zz-99")
    assert r.status_code == 400


def test_syllabus_endpoint(client):
    r = client.get("/syllabus/alex/de")
    assert r.status_code == 200
    body = r.json()
    assert body["levels"][0]["level"] == "A1"
    assert body["next"]["id"] == "a1-01"
    assert client.get("/syllabus/nobody/de").status_code == 404


def _analyst_returning(monkeypatch, topic_status: str):
    from backend.services import llm as llm_srv

    async def fake_analyst(messages, **kw):
        return json.dumps(
            {
                "progress_note": "Short session.",
                "vocab": [],
                "missed_opportunities": [],
                "topic_status": topic_status,
            }
        )

    monkeypatch.setattr(llm_srv, "chat", fake_analyst)


def test_mode9_turn_uses_the_teacher_output(client):
    sid = _start_lesson(client, topic_id="a1-01").json()["session_id"]
    r = client.post("/turn", data={"session_id": sid, "text": "Hallo, ich bin Alex"})
    assert r.status_code == 200, r.text
    assert client.llm_calls[-1].get("output") == "teacher"


def test_post_session_mode9_updates_status(client, monkeypatch):
    sid = _start_lesson(client, topic_id="a1-01").json()["session_id"]
    # one turn so the day has a transcript
    client.post("/turn", data={"session_id": sid, "text": "Hallo, ich bin Alex"})
    _analyst_returning(monkeypatch, "practiced")
    r = client.post("/session/end", json={"session_id": sid})
    assert r.status_code == 200
    assert syllabus.read_user_syllabus("alex", "de")["a1-01"]["status"] == "practiced"


def test_post_session_mode9_invalid_status_is_ignored(client, monkeypatch):
    # the analyst returns a status outside the scale: nothing breaks or changes
    sid = _start_lesson(client, topic_id="a1-01").json()["session_id"]
    client.post("/turn", data={"session_id": sid, "text": "Hallo"})
    _analyst_returning(monkeypatch, "perfect")
    r = client.post("/session/end", json={"session_id": sid})
    assert r.status_code == 200
    assert syllabus.read_user_syllabus("alex", "de")["a1-01"]["status"] == "seen"
