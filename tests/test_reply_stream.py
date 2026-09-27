"""Tests for ReplyStreamExtractor: splitting `reply` into sentences for TTS while
the stream arrives. Sensitive to how the model splits the deltas (escapes, \\uXXXX)."""

from backend.reply_stream import ReplyStreamExtractor


def feed_all(deltas, min_chunk_chars=25):
    ex = ReplyStreamExtractor(min_chunk_chars=min_chunk_chars)
    chunks = []
    for d in deltas:
        chunks.extend(ex.feed(d))
    tail = ex.finish()
    return ex, chunks, tail


def test_complete_sentences_in_order():
    raw = '{"reply": "Hallo Alex, schön dich zu sehen! Wie war dein Tag im Büro heute? Erzähl mir mehr davon.", "corrections": []}'
    # 7-char deltas simulate the stream.
    deltas = [raw[i : i + 7] for i in range(0, len(raw), 7)]
    ex, chunks, tail = feed_all(deltas)
    assert ex.found_reply
    text = " ".join(chunks + ([tail] if tail else []))
    assert text.startswith("Hallo Alex")
    assert "Erzähl mir mehr davon." in text
    # No chunk contains JSON quotes or contract keys.
    assert all('"' not in c for c in chunks)


def test_does_not_split_short_abbreviations():
    raw = '{"reply": "z.B. so etwas kannst du sagen, wenn du ein Beispiel geben willst."}'
    _ex, chunks, tail = feed_all([raw], min_chunk_chars=25)
    joined = " ".join(chunks + ([tail] if tail else []))
    # "z.B." must not come out as a tiny standalone clip.
    assert all(len(c.strip()) >= 25 for c in chunks)
    assert "z.B. so etwas" in joined


def test_delta_splits_an_escape():
    # The delta cuts right between '\' and 'n'.
    part1 = '{"reply": "Erste Zeile hier ist lang genug zum Flushen.\\'
    part2 = 'nZweite Zeile kommt danach und ist auch lang."}'
    _ex, chunks, tail = feed_all([part1, part2])
    joined = "\n".join(chunks + ([tail] if tail else []))
    assert "Erste Zeile hier ist lang genug zum Flushen." in joined
    assert "Zweite Zeile" in joined


def test_delta_splits_a_unicode_escape():
    # ö (ö) split across two deltas: decoding must wait for the full escape.
    part1 = '{"reply": "Das W\\u00f'
    part2 = '6rterbuch liegt auf dem Tisch. Nimm es ruhig mit nach Hause heute."}'
    _ex, chunks, tail = feed_all([part1, part2])
    joined = " ".join(chunks + ([tail] if tail else []))
    assert "Wörterbuch" in joined


def test_without_reply_degrades():
    ex, chunks, tail = feed_all(["Hallo, das ist reiner Text ohne JSON."])
    assert not ex.found_reply
    assert chunks == [] and tail is None
    # The caller uses .raw to degrade (it synthesizes the full text).
    assert "reiner Text" in ex.raw


def test_finish_returns_pending_tail():
    raw = '{"reply": "Kurz und knapp ohne Schlusspunkt am Ende gesagt"}'
    _ex, chunks, tail = feed_all([raw])
    assert chunks == []
    assert tail == "Kurz und knapp ohne Schlusspunkt am Ende gesagt"


def test_closing_the_value_does_not_drag_the_rest_of_the_json():
    raw = '{"reply": "Nur dieser Satz gehört in die Sprachausgabe, sonst nichts!", "corrections": [{"original": "a", "corrected": "b"}]}'
    _ex, chunks, tail = feed_all([raw])
    joined = " ".join(chunks + ([tail] if tail else []))
    assert "corrections" not in joined
    assert "corrected" not in joined
