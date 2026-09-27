"""Tests for the book entity (backend/books.py) and the mode 8 flow."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import books, config, memory
from backend.services import llm, stt, tts
from backend.sessions import SESSIONS

PAGE_TEXT = "Jonas stellte zwei leere Tassen auf den Tisch."


@pytest.fixture()
def mem(monkeypatch, tmp_path, make_learner):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    make_learner(data_dir, cefr="A2", languages=("de",))
    return data_dir


def test_create_and_list(mem):
    meta = books.create_book("alex", "de", "Sommer am Kanal")
    assert meta["slug"] == "sommer-am-kanal"
    assert meta["title"] == "Sommer am Kanal"
    assert meta["page"] == 0 and meta["status"] == "active" and meta["sessions"] == 0
    lst = books.list_books("alex", "de")
    assert len(lst) == 1 and lst[0]["slug"] == "sommer-am-kanal"


def test_book_file_sections(mem):
    books.create_book("alex", "de", "My book")
    text = (mem / "alex" / "de" / "books" / "my-book.md").read_text(encoding="utf-8")
    assert "## Thread summary" in text and "## History" in text
    assert "status: active" in text


def test_create_duplicate_title_adds_suffix(mem):
    a = books.create_book("alex", "de", "My book")
    b = books.create_book("alex", "de", "My book")
    assert a["slug"] == "my-book" and b["slug"] == "my-book-2"


def test_create_title_without_letters_falls_back_to_untitled(mem):
    assert books.create_book("alex", "de", "!!!")["slug"] == "untitled"


def test_read_missing_book(mem):
    assert books.read_book("alex", "de", "nothing") is None


def test_update_book(mem):
    books.create_book("alex", "de", "My book")
    books.update_book(
        "alex",
        "de",
        "my-book",
        page=12,
        summary="Lena arrives at the harbour and meets Jonas.",
        history_line="p.12 · read aloud 84%",
    )
    book = books.read_book("alex", "de", "my-book")
    assert book["page"] == 12 and book["sessions"] == 1
    assert "Jonas" in book["summary"]
    assert any("p.12" in h for h in book["history"])
    # Second session: the summary is REPLACED, the history accumulates.
    books.update_book("alex", "de", "my-book", page=13, summary="New summary.", history_line="p.13")
    book = books.read_book("alex", "de", "my-book")
    assert book["summary"] == "New summary." and book["sessions"] == 2
    assert len(book["history"]) == 2 and "p.13" in book["history"][0]  # most recent first


def test_valid_slug():
    assert books.valid_slug("my-book-2")
    assert not books.valid_slug("../etc")
    assert not books.valid_slug("")


def test_vocab_for_book_filters_by_tag(mem):
    memory.append_vocab("alex", "de", "\n## 2026-07-01\n- **die Reise**: the trip\n")
    memory.append_vocab(
        "alex",
        "de",
        "\n## 2026-07-05 (book: my-book)\n- **die Tasse**: the cup\n- **aufräumen**: to tidy up\n",
    )
    memory.append_vocab("alex", "de", "\n## 2026-07-06 (book: other)\n- **der Zug**: the train\n")
    terms = memory.vocab_for_book("alex", "de", "my-book")
    assert terms == ["**die Tasse**: the cup", "**aufräumen**: to tidy up"]


@pytest.fixture()
def client(mem, monkeypatch, tmp_path):
    audio_root = tmp_path / "audio"
    audio_root.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "AUDIO_ROOT", audio_root)
    from backend.app import app

    return TestClient(app)


def test_books_endpoints(client):
    r = client.post("/books/alex/de", json={"title": "Der Leuchtturm im Nebel"})
    assert r.status_code == 200
    created = r.json()
    slug = created["slug"]
    assert slug == "der-leuchtturm-im-nebel"
    # The POST must return the same shape as the detail (with 'vocab'), or the
    # frontend crashes reading book.vocab.length on a freshly created book.
    assert created["vocab"] == []

    r = client.get("/books/alex/de")
    assert r.status_code == 200
    assert r.json()["books"][0]["slug"] == slug

    memory.append_vocab("alex", "de", f"\n## 2026-07-05 (book: {slug})\n- **die Tasse**: the cup\n")
    r = client.get(f"/books/alex/de/{slug}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["title"] == "Der Leuchtturm im Nebel"
    assert detail["vocab"] == ["**die Tasse**: the cup"]

    assert client.get("/books/alex/de/does-not-exist").status_code == 404
    assert client.get("/books/alex/de/Bad_Slug").status_code == 400
    assert client.post("/books/alex/de", json={"title": "  "}).status_code == 400


@pytest.fixture()
def client_mode8(client, monkeypatch):
    """Client with chat/STT/TTS mocked for the mode 8 session flow."""
    contract = {
        "reply": "Gut gelesen! Warum stellt Jonas die Tassen auf den Tisch?",
        "corrections": [],
        "new_vocab": [],
        "suggested_followup": "Was denkst du?",
    }

    async def fake_chat(messages, temperature=None, max_tokens=None, **kwargs):
        return json.dumps(contract, ensure_ascii=False)

    async def fake_chat_stream(messages, temperature=None, max_tokens=None, **kwargs):
        yield json.dumps(contract, ensure_ascii=False)

    async def fake_warmup(system_prompt=None, **kwargs):
        return None

    async def fake_synthesize(text, language, voice=None, length_scale=None):
        return b"RIFFfake"

    async def fake_transcribe_words(
        audio, language, filename="read.wav", content_type=None, prompt=None
    ):
        return "Jonas stellte zwei Tassen", [
            {"word": "Jonas", "probability": 0.95},
            {"word": "stellte", "probability": 0.9},
            {"word": "zwei", "probability": 0.3},
            {"word": "Tassen", "probability": 0.9},
        ]

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(llm, "warmup", fake_warmup)
    monkeypatch.setattr(tts, "synthesize", fake_synthesize)
    monkeypatch.setattr(stt, "transcribe_words", fake_transcribe_words)
    SESSIONS.clear()
    yield client
    SESSIONS.clear()


def _start_mode8(client):
    client.post("/books/alex/de", json={"title": "My book"})
    return client.post(
        "/session/start",
        json={
            "user_id": "alex",
            "target_language": "de",
            "mode": 8,
            "book_slug": "my-book",
            "page": 12,
            "context": PAGE_TEXT,
            "defer_opening": True,
        },
    )


def _read_aloud(client, sid):
    return client.post(
        "/read/score",
        data={"session_id": sid},
        files={"audio": ("read.webm", b"fakeaudio", "audio/webm")},
    )


def test_mode8_start(client_mode8):
    r = _start_mode8(client_mode8)
    assert r.status_code == 200
    data = r.json()
    assert data["reference_text"] == PAGE_TEXT
    assert data["opening"] is None and data["opening_pending"] is False
    sp = data["system_prompt"]
    assert "My book" in sp and "## Page text" in sp


def test_mode8_start_validates_book(client_mode8):
    r = client_mode8.post(
        "/session/start",
        json={
            "user_id": "alex",
            "target_language": "de",
            "mode": 8,
            "book_slug": "does-not-exist",
            "page": 1,
            "context": "x",
        },
    )
    assert r.status_code == 404


def test_mode8_read_score_and_kickoff(client_mode8):
    sid = _start_mode8(client_mode8).json()["session_id"]
    # /read/score accepts mode 8 and does not block the later kickoff.
    r = _read_aloud(client_mode8, sid)
    assert r.status_code == 200
    assert SESSIONS[sid].get("read_note")  # context for the opening
    # Comprehension kickoff AFTER the reading (turns is already > 0).
    r = client_mode8.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    assert r.status_code == 200
    body = r.text
    assert '"type": "meta"' in body or '"type":"meta"' in body
    # A second kickoff is rejected (the session already opened).
    r = client_mode8.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    assert r.status_code == 400


def test_mode8_read_only_saves_the_book(client_mode8):
    """Pronunciation only + end (without comprehension) MUST save the book:
    page + history with the score. Regression: the model summary ran before the
    write and its failure swallowed the save."""
    sid = _start_mode8(client_mode8).json()["session_id"]
    _read_aloud(client_mode8, sid)
    # End WITHOUT kickoff (no comprehension).
    r = client_mode8.post("/session/end", json={"session_id": sid})
    assert r.status_code == 200

    book = books.read_book("alex", "de", "my-book")
    assert book["page"] == 12 and book["sessions"] == 1
    assert any("read aloud" in h for h in book["history"])


def test_mode8_close_updates_the_book(client_mode8, monkeypatch):
    from backend import post_session

    responses = iter(
        [
            # 1st call: normal session summary.
            {
                "progress_note": "- Good reading.",
                "vocab": [
                    {"term": "die Tasse", "translation": "the cup", "example": "Zwei Tassen."}
                ],
                "missed_opportunities": [],
            },
            # 2nd call: book summary (there is no skill tracker, so it is skipped).
            {"summary": "Jonas sets the table and the narrator thinks it over."},
            {"summary": "Jonas sets the table and the narrator thinks it over."},
        ]
    )

    async def fake_analyst(instruction, payload, *, max_tokens, label, temperature=0.2, **kwargs):
        try:
            return next(responses)
        except StopIteration:
            return {}

    monkeypatch.setattr(post_session, "_analyst_json", fake_analyst)

    sid = _start_mode8(client_mode8).json()["session_id"]
    _read_aloud(client_mode8, sid)
    client_mode8.post("/turn/stream", data={"session_id": sid, "kickoff": "1"})
    r = client_mode8.post("/session/end", json={"session_id": sid})
    assert r.status_code == 200

    book = books.read_book("alex", "de", "my-book")
    assert book["page"] == 12 and book["sessions"] == 1
    assert "Jonas" in book["summary"]
    # The session vocabulary was tagged with the book.
    assert memory.vocab_for_book("alex", "de", "my-book")


# ---------------------------------------------------------------------------
# End page: where the learner really stopped, not where she started.
# ---------------------------------------------------------------------------
def test_end_page_saves_the_page_where_she_stopped(client_mode8):
    """Reading several pages used to store the START page.

    With "Add another page" the learner moves on within the same session, so
    the start page stops being true as soon as she goes past the first one.
    """
    sid = _start_mode8(client_mode8).json()["session_id"]
    # Without activity the close does not touch the book: read, as in real life.
    _read_aloud(client_mode8, sid)
    r = client_mode8.post("/session/end", json={"session_id": sid, "end_page": 15})
    assert r.status_code == 200
    assert books.read_book("alex", "de", "my-book")["page"] == 15


def test_without_end_page_the_old_behaviour_is_kept(client_mode8):
    """Whoever does not answer the question must not lose out: the start page counts."""
    sid = _start_mode8(client_mode8).json()["session_id"]
    _read_aloud(client_mode8, sid)
    client_mode8.post("/session/end", json={"session_id": sid})
    assert books.read_book("alex", "de", "my-book")["page"] == 12


def test_absurd_end_page_is_ignored(client_mode8):
    """A zero or a negative cannot wipe the real progress of the book."""
    sid = _start_mode8(client_mode8).json()["session_id"]
    _read_aloud(client_mode8, sid)
    client_mode8.post("/session/end", json={"session_id": sid, "end_page": 0})
    assert books.read_book("alex", "de", "my-book")["page"] == 12
