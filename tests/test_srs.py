"""Tests for the SRS module (backend/srs.py): sync from vocab.md, due cards,
FSRS review, weak_terms and atomic persistence. Offline: FSRS is pure and the
data goes to tmp_path."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from backend import config, srs

VOCAB_MD = """# Vocabulary

## 2026-07-01
- **die Bordkarte**: boarding pass _(e.g. Hier ist meine Bordkarte.)_
- **spannend**: exciting
- **der Zoll**: customs _(e.g. Der Zoll prüft das Gepäck.)_
"""


@pytest.fixture()
def mem(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    d = tmp_path / "alex" / "de"
    d.mkdir(parents=True)
    (d / "vocab.md").write_text(VOCAB_MD, encoding="utf-8")
    return tmp_path


def test_sync_from_vocab(mem):
    result = srs.sync_from_vocab("alex", "de")
    assert result == {"added": 3, "total": 3}
    cards = srs.load("alex", "de")["cards"]
    # Normalized key (no article, lower case), original term kept.
    assert set(cards) == {"bordkarte", "spannend", "zoll"}
    rec = cards["bordkarte"]
    assert rec["term"] == "die Bordkarte"
    assert rec["translation"] == "boarding pass"
    assert rec["example"] == "Hier ist meine Bordkarte."
    assert rec["last_review"] is None
    assert rec["fsrs"]["due"]  # serialized FSRS card
    # Entry without example: clean translation, empty example.
    assert cards["spannend"]["translation"] == "exciting"
    assert cards["spannend"]["example"] == ""
    # Idempotent: a re-sync neither duplicates nor resets.
    fsrs_before = rec["fsrs"]
    assert srs.sync_from_vocab("alex", "de") == {"added": 0, "total": 3}
    assert srs.load("alex", "de")["cards"]["bordkarte"]["fsrs"] == fsrs_before


def test_initial_due_new_cards_are_due_now(mem):
    srs.sync_from_vocab("alex", "de")
    payload = srs.due_payload("alex", "de")
    assert payload["total_cards"] == 3
    assert payload["due_count"] == 3
    assert len(payload["due"]) == 3
    item = payload["due"][0]
    assert set(item) == {"term", "translation", "example", "due"}
    # Sorted by ascending due date.
    dues = [datetime.fromisoformat(i["due"]) for i in payload["due"]]
    assert dues == sorted(dues)


def test_review_good_postpones_due(mem):
    srs.sync_from_vocab("alex", "de")
    before = datetime.fromisoformat(srs.load("alex", "de")["cards"]["bordkarte"]["fsrs"]["due"])
    result = srs.review("alex", "de", "die Bordkarte", 3)
    assert result["term"] == "die Bordkarte"
    next_due = datetime.fromisoformat(result["next_due"])
    assert next_due > before
    # Persisted on disk and reloadable.
    rec = srs.load("alex", "de")["cards"]["bordkarte"]
    assert rec["fsrs"]["due"] == result["next_due"]
    assert rec["last_review"] is not None
    assert rec["lapses"] == 0


def test_review_again_records_lapse(mem):
    srs.sync_from_vocab("alex", "de")
    srs.review("alex", "de", "spannend", 1)
    rec = srs.load("alex", "de")["cards"]["spannend"]
    assert rec["lapses"] == 1
    assert rec["last_lapse"] is not None


def test_review_unknown_term(mem):
    srs.sync_from_vocab("alex", "de")
    with pytest.raises(KeyError):
        srs.review("alex", "de", "nonexistent", 3)


def test_weak_terms(mem):
    srs.sync_from_vocab("alex", "de")
    # All new => all due => all weak.
    weak = srs.weak_terms("alex", "de")
    assert set(weak) == {"die Bordkarte", "spannend", "der Zoll"}
    assert srs.weak_terms("alex", "de", n=2) == weak[:2]
    # Easy sends the card to the future: it is no longer due... but a recent
    # lapse keeps it weak.
    srs.review("alex", "de", "der Zoll", 1)  # lapse
    srs.review("alex", "de", "der Zoll", 4)  # Easy: due in days
    data = srs.load("alex", "de")
    zoll_due = datetime.fromisoformat(data["cards"]["zoll"]["fsrs"]["due"])
    assert zoll_due > datetime.now(UTC)
    assert "der Zoll" in srs.weak_terms("alex", "de")


def test_weak_terms_without_srs_json(mem):
    assert srs.weak_terms("alex", "de") == []


def test_atomic_persistence(mem):
    srs.sync_from_vocab("alex", "de")
    path = srs.srs_path("alex", "de")
    assert path.is_file()
    # No leftover tmp file, and the file is valid JSON with the expected shape.
    assert list(path.parent.glob("*.tmp")) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["cards"]) == {"bordkarte", "spannend", "zoll"}
    # Identical round trip on reload.
    assert srs.load("alex", "de") == data


def test_memory_block_includes_vocabulary_to_reinforce(mem):
    from backend import memory

    srs.sync_from_vocab("alex", "de")
    block = memory.build_memory_block("alex", "de")
    assert "### Vocabulary to reinforce (spaced repetition)" in block
    assert "die Bordkarte" in block
    # Without srs.json the section does not appear.
    srs.srs_path("alex", "de").unlink()
    assert "spaced repetition" not in memory.build_memory_block("alex", "de")
