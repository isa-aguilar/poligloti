"""Tests for score_reading (mode 4): reference/transcript alignment + thresholds."""

from backend import config
from backend.pronunciation import score_reading


def hw(word, prob):
    return {"word": word, "probability": prob}


def test_perfect_reading():
    ref = "Der Zug fährt pünktlich ab."
    heard = [
        hw("Der", 0.95),
        hw("Zug", 0.9),
        hw("fährt", 0.92),
        hw("pünktlich", 0.88),
        hw("ab", 0.9),
    ]
    out = score_reading(ref, heard)
    assert out["summary"]["total"] == 5
    assert out["summary"]["ok"] == 5
    assert out["summary"]["accuracy"] == 100
    assert out["flagged"] == []


def test_weak_and_miss_thresholds_by_confidence():
    ref = "Hallo Welt heute"
    heard = [
        hw("Hallo", config.READ_WORD_PROB_OK),  # exactly on the ok threshold
        hw("Welt", config.READ_WORD_PROB_WEAK),  # exactly on the weak threshold
        hw("heute", config.READ_WORD_PROB_WEAK - 0.01),  # below -> miss
    ]
    out = score_reading(ref, heard)
    statuses = [w["status"] for w in out["words"]]
    assert statuses == ["ok", "weak", "miss"]
    assert out["flagged"] == ["Welt", "heute"]


def test_prob_none_counts_as_ok():
    out = score_reading("Hallo", [hw("Hallo", None)])
    assert out["words"][0]["status"] == "ok"


def test_replace_marks_miss_and_records_what_was_heard():
    ref = "Ich gehe zur Schule"
    heard = [hw("Ich", 0.9), hw("gehe", 0.9), hw("zum", 0.9), hw("Schule", 0.9)]
    out = score_reading(ref, heard)
    zur = out["words"][2]
    assert zur["status"] == "miss"
    assert zur["heard"] == "zum"


def test_delete_unread_word_is_miss():
    ref = "Das ist ein sehr schöner Tag"
    heard = [hw("Das", 0.9), hw("ist", 0.9), hw("ein", 0.9), hw("schöner", 0.9), hw("Tag", 0.9)]
    out = score_reading(ref, heard)
    sehr = next(w for w in out["words"] if w["text"] == "sehr")
    assert sehr["status"] == "miss"
    assert out["summary"]["ok"] == 5


def test_insert_extra_words_are_ignored():
    ref = "Guten Morgen"
    heard = [hw("Guten", 0.9), hw("ähm", 0.9), hw("Morgen", 0.9)]
    out = score_reading(ref, heard)
    assert [w["status"] for w in out["words"]] == ["ok", "ok"]


def test_punctuation_and_case_do_not_matter():
    ref = "Hallo, Welt!"
    heard = [hw("hallo", 0.9), hw("welt", 0.9)]
    out = score_reading(ref, heard)
    assert out["summary"]["ok"] == 2


def test_flagged_dedup_keeps_order():
    ref = "rot rot blau"
    heard = []  # nothing heard: everything is a miss
    out = score_reading(ref, heard)
    assert out["flagged"] == ["rot", "blau"]


def test_empty_reference():
    out = score_reading("", [])
    assert out["summary"]["total"] == 0
    assert out["summary"]["accuracy"] == 0
