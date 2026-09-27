"""Tests for levelled stories (backend/stories.py + router): create with a
mocked model, list, next chapter (with previous summaries in the prompt),
detail and slug validation. Offline: the chat service is mocked."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.services import llm

CH1 = {
    "title": "Der geheimnisvolle Koffer",
    "chapter": (
        "Nora arbeitet am Bahnhof. Heute findet sie einen alten Koffer auf "
        "Gleis drei. Niemand kennt den Besitzer. Was ist wohl darin?"
    ),
    "summary": "Nora findet einen herrenlosen Koffer am Bahnhof und will ihn öffnen.",
}
CH2 = {
    "chapter": (
        "Nora öffnet den Koffer langsam. Darin liegt eine alte Landkarte mit "
        "einem roten Kreuz. Sie beschließt, dem Weg zu folgen."
    ),
    "summary": "Im Koffer liegt eine Landkarte mit einem roten Kreuz.",
}


@pytest.fixture()
def client(monkeypatch, tmp_path, make_learner):
    data_dir = tmp_path / "data"
    audio_root = tmp_path / "audio"
    audio_root.mkdir(parents=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "AUDIO_ROOT", audio_root)
    make_learner(data_dir, cefr="B1")

    calls: list[dict] = []
    responses = [CH1, CH2]

    async def fake_chat(messages, temperature=None, max_tokens=None, **kwargs):
        calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "output": kwargs.get("output"),
            }
        )
        reply = responses[min(len(calls) - 1, len(responses) - 1)]
        return json.dumps(reply, ensure_ascii=False)

    monkeypatch.setattr(llm, "chat", fake_chat)

    from backend.app import app

    with TestClient(app) as c:
        c.llm_calls = calls
        yield c


def _prompt_text(call: dict) -> str:
    return "\n".join(m["content"] for m in call["messages"])


def test_create_story(client):
    resp = client.post("/stories/alex/de", json={"topic": "a train journey"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["slug"] == "der-geheimnisvolle-koffer"
    assert data["title"] == CH1["title"]
    assert data["level"] == "B1"
    assert data["chapter"] == 1
    assert data["text"] == CH1["chapter"]
    # The prompt carries the learner's CEFR level and the requested topic.
    prompt = _prompt_text(client.llm_calls[0])
    assert "B1" in prompt
    assert "a train journey" in prompt
    assert client.llm_calls[0]["temperature"] == 0.7
    assert client.llm_calls[0]["output"] == "json"
    # Markdown file created with frontmatter + summary in an HTML comment.
    md = (config.DATA_DIR / "alex" / "de" / "stories" / f"{data['slug']}.md").read_text(
        encoding="utf-8"
    )
    assert "title: Der geheimnisvolle Koffer" in md
    assert "level: B1" in md
    assert "## Chapter 1" in md
    assert f"<!-- summary: {CH1['summary']} -->" in md


def test_list_stories(client):
    assert client.get("/stories/alex/de").json() == []
    client.post("/stories/alex/de", json={"topic": "train"})
    stories = client.get("/stories/alex/de").json()
    assert len(stories) == 1
    s = stories[0]
    assert s["slug"] == "der-geheimnisvolle-koffer"
    assert s["title"] == CH1["title"]
    assert s["level"] == "B1"
    assert s["chapters"] == 1
    assert s["updated"]


def test_next_chapter_uses_previous_summaries(client):
    slug = client.post("/stories/alex/de", json={}).json()["slug"]
    resp = client.post(f"/stories/alex/de/{slug}/next")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == {"slug": slug, "chapter": 2, "text": CH2["chapter"]}
    # The chapter 2 prompt includes the chapter 1 summary (not the whole text).
    prompt = _prompt_text(client.llm_calls[1])
    assert CH1["summary"] in prompt
    assert CH1["title"] in prompt
    assert "chapter 2" in prompt.lower()
    # And the list reflects the 2 chapters.
    assert client.get("/stories/alex/de").json()[0]["chapters"] == 2


def test_story_detail(client):
    slug = client.post("/stories/alex/de", json={"topic": "train"}).json()["slug"]
    client.post(f"/stories/alex/de/{slug}/next")
    resp = client.get(f"/stories/alex/de/{slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == slug
    assert data["title"] == CH1["title"]
    assert data["level"] == "B1"
    assert [ch["n"] for ch in data["chapters"]] == [1, 2]
    assert data["chapters"][0]["text"] == CH1["chapter"]
    assert data["chapters"][1]["text"] == CH2["chapter"]
    # The summary is internal (model context) and is not served to the frontend.
    assert "summary" not in json.dumps(data)


def test_invalid_and_missing_slug(client):
    # Slug with characters outside [a-z0-9-]: 400.
    assert client.get("/stories/alex/de/Not_Valid").status_code == 400
    assert client.post("/stories/alex/de/Not_Valid/next").status_code == 400
    # Valid but nonexistent slug: 404.
    assert client.get("/stories/alex/de/does-not-exist").status_code == 404
    assert client.post("/stories/alex/de/does-not-exist/next").status_code == 404
    # Invalid user/lang: 400 (validate_ids).
    assert client.get("/stories/alex/xx").status_code == 400


def test_create_story_weaves_in_weak_terms(client):
    from backend import srs

    (config.DATA_DIR / "alex" / "de" / "vocab.md").write_text(
        "# Vocabulary\n\n- **die Bordkarte**: boarding pass\n",
        encoding="utf-8",
    )
    srs.sync_from_vocab("alex", "de")
    resp = client.post("/stories/alex/de", json={})
    assert resp.status_code == 200
    prompt = _prompt_text(client.llm_calls[0])
    assert "die Bordkarte" in prompt
