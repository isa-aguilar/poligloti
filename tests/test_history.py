"""Session history: turns grouped by session, notes of the closing pass."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import config, memory, post_session, session_log
from backend.services import llm, status

REPLY = json.dumps(
    {
        "reply": "Schön! Was hast du gegessen?",
        "corrections": [
            {
                "original": "ich habe gegangen",
                "corrected": "ich bin gegangen",
                "note": "movement: sein",
            }
        ],
        "new_vocab": [{"term": "die Speisekarte", "translation": "the menu"}],
        "suggested_followup": "Erzähl mir vom Essen.",
    }
)


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr(config, "AUDIO_ROOT", data_dir / ".audio")
    monkeypatch.setattr(config, "AI_BASE_URL", "http://chat.test/v1")
    monkeypatch.setattr(config, "AI_MODEL", "chat-model")

    async def fake_chat(messages, temperature=None, max_tokens=None, output="text", **kw):
        if output == "json":
            return json.dumps(
                {
                    "progress_note": "- Uses haben with movement verbs.",
                    "vocab": [
                        {"term": "die Speisekarte", "translation": "the menu", "example": ""}
                    ],
                    "missed_opportunities": ["lecker (tasty)"],
                }
            )
        return REPLY

    async def no_warmup(*a, **kw):
        return None

    async def no_probe() -> None:
        return None

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "warmup", no_warmup)
    monkeypatch.setattr(status, "safe_probe", no_probe)
    with TestClient(app_module.app) as c:
        yield c


def _session(client, text: str) -> str:
    sid = client.post(
        "/session/start", json={"user_id": "alex", "target_language": "de", "mode": 1}
    ).json()["session_id"]
    assert client.post("/turn", data={"session_id": sid, "text": text}).status_code == 200
    return sid


def test_two_sessions_on_the_same_day_are_listed_apart(client):
    first = _session(client, "Gestern ich habe gegangen ins Restaurant.")
    client.post("/session/end", json={"session_id": first})
    second = _session(client, "Heute bin ich müde.")

    listed = client.get("/sessions/alex/de").json()["sessions"]
    assert [s["id"] for s in listed] == [second, first]
    assert listed[1]["turns"] == 1 and listed[1]["mode"] == 1
    assert listed[1]["has_notes"] is True and listed[0]["has_notes"] is False
    assert listed[1]["preview"].startswith("Gestern")


def test_session_detail_has_turns_corrections_and_notes(client):
    sid = _session(client, "Gestern ich habe gegangen ins Restaurant.")
    client.post("/session/end", json={"session_id": sid})

    body = client.get(f"/sessions/alex/de/{sid}").json()
    turn = body["turns"][0]
    assert turn["learner"].startswith("Gestern")
    assert turn["teacher"] == "Schön! Was hast du gegessen?"
    assert turn["corrections"] == [
        {"original": "ich habe gegangen", "corrected": "ich bin gegangen", "note": "movement: sein"}
    ]
    assert turn["new_vocab"] == [{"term": "die Speisekarte", "translation": "the menu"}]
    assert turn["suggestion"] == "Erzähl mir vom Essen."
    assert body["notes"]["summary"].startswith("- Uses haben")
    assert body["notes"]["missed_opportunities"] == ["lecker (tasty)"]


def test_the_analyst_only_reads_its_own_session(client, monkeypatch):
    other = _session(client, "Das ist eine andere Sitzung.")
    sid = _session(client, "Gestern ich habe gegangen ins Restaurant.")
    seen: list[str] = []

    async def spy(instruction, payload, **kw):
        seen.append(payload)
        return {}

    monkeypatch.setattr(post_session, "_analyst_json", spy)
    client.post("/session/end", json={"session_id": sid})
    assert seen and all("andere Sitzung" not in p for p in seen)
    assert other  # the other session is still open and untouched


def test_logs_written_before_session_ids_group_by_day(data_dir):
    day = data_dir / "alex" / "de" / "sessions"
    day.mkdir(parents=True, exist_ok=True)
    (day / "2026-01-05.md").write_text(
        "# Session 2026-01-05 (alex / de)\n\n"
        "## Turn 10:00:00 (mode 2 · work/kpi-meeting)\n"
        "- **Learner**: (teacher opening)\n"
        "- **Teacher**: Guten Morgen.\n"
        "- **Corrections**:\n  - (none)\n"
        "- **New vocabulary**:\n  - (none)\n"
        "- **Suggestion**: \n",
        encoding="utf-8",
    )
    listed = session_log.list_sessions("alex", "de")
    assert listed[0]["id"] == "day-2026-01-05"
    assert listed[0]["label"] == "work/kpi-meeting"
    detail = session_log.read_session("alex", "de", "day-2026-01-05")
    assert detail["turns"][0]["learner"] == ""  # the placeholder is not something the learner said
    assert detail["notes"] is None


def test_unknown_and_invalid_sessions(client):
    assert client.get("/sessions/alex/de/nope").status_code == 404
    assert client.get("/sessions/alex/de/bad..id").status_code == 400
    assert client.get("/sessions/alex/de").json() == {"sessions": []}


def test_read_session_day_filters_by_session(data_dir):
    memory.append_turn("alex", "de", 1, {"transcript": "eins", "reply": "a"}, session_id="s1")
    memory.append_turn("alex", "de", 1, {"transcript": "zwei", "reply": "b"}, session_id="s2")
    only = memory.read_session_day("alex", "de", session_id="s2")
    assert "zwei" in only and "eins" not in only
    assert "eins" in memory.read_session_day("alex", "de")
