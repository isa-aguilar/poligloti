"""Tests for parse_teacher_reply: the piece that shields the UX from any format
drift of the model. When the model changes, this is the first thing to fail."""

import json

from backend.llm_parse import drop_stale_corrections, extract_json_object, parse_teacher_reply

CONTRACT = {
    "reply": "Hallo Alex! Wie geht es dir heute?",
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
    "suggested_followup": "Was hast du am Wochenende gemacht?",
    "revised": "",
}


def test_clean_json():
    out = parse_teacher_reply(json.dumps(CONTRACT, ensure_ascii=False))
    assert out["reply"] == CONTRACT["reply"]
    assert out["corrections"][0]["corrected"] == "Ich bin gegangen"
    assert out["new_vocab"][0]["term"] == "die Bordkarte"
    assert out["suggested_followup"] == CONTRACT["suggested_followup"]


def test_wrapped_in_fences_and_prose():
    raw = "Sure, here you go:\n```json\n" + json.dumps(CONTRACT, ensure_ascii=False) + "\n```\n"
    out = parse_teacher_reply(raw)
    assert out["reply"] == CONTRACT["reply"]
    assert len(out["corrections"]) == 1


def test_prefer_key_ignores_earlier_inner_object():
    # An object without `reply` before the contract (e.g. a stray correction).
    raw = '{"original": "x", "corrected": "y"} ' + json.dumps(CONTRACT, ensure_ascii=False)
    out = parse_teacher_reply(raw)
    assert out["reply"] == CONTRACT["reply"]


def test_markdown_drift_salvages_fields_and_trims_tail():
    raw = (
        "Hallo! Das war ein guter Satz.\n\n"
        '**corrections**: [{"original": "das Haus rot", "corrected": "das rote Haus", "note": "word order"}]\n'
        '**new_vocab**: [{"term": "der Zug", "translation": "train", "example": "Der Zug ist pünktlich."}]\n'
        '**suggested_followup**: "Fährst du oft mit dem Zug?"\n'
    )
    out = parse_teacher_reply(raw)
    # The contract tail must NOT be read aloud.
    assert out["reply"] == "Hallo! Das war ein guter Satz."
    assert "corrections" not in out["reply"]
    assert out["corrections"][0]["corrected"] == "das rote Haus"
    assert out["new_vocab"][0]["term"] == "der Zug"
    assert out["suggested_followup"] == "Fährst du oft mit dem Zug?"


def test_json_truncated_by_max_tokens_does_not_lose_the_turn():
    # The stream stops halfway through new_vocab: the object is not valid JSON.
    raw = (
        '{"reply": "Guten Morgen! Heute sprechen wir über das Wetter.", '
        '"corrections": [], "new_vocab": [{"term": "die Wol'
    )
    out = parse_teacher_reply(raw)
    # Degrades: never an empty turn, and the contract never leaks into speech.
    assert "Guten Morgen! Heute sprechen wir über das Wetter." in out["reply"]
    assert '"new_vocab"' not in out["reply"]


def test_plain_prose_degrades_to_raw_text():
    raw = "Hallo Alex, wie war dein Tag?"
    out = parse_teacher_reply(raw)
    assert out["reply"] == raw
    assert out["corrections"] == []
    assert out["new_vocab"] == []


def test_corrections_as_strings_and_cap():
    data = dict(CONTRACT)
    data["corrections"] = ["err one", "err two", "err three", "err four", "err five"]
    out = parse_teacher_reply(json.dumps(data, ensure_ascii=False))
    # MAX_CORRECTIONS=3 and strings are normalized into a note.
    assert len(out["corrections"]) == 3
    assert out["corrections"][0]["note"] == "err one"


def test_vocab_without_term_is_dropped():
    data = dict(CONTRACT)
    data["new_vocab"] = [
        {"translation": "no term"},
        {"term": " ", "translation": "empty"},
        "just-a-string",
    ]
    out = parse_teacher_reply(json.dumps(data, ensure_ascii=False))
    assert out["new_vocab"] == [{"term": "just-a-string", "translation": "", "example": ""}]


def test_extract_json_object_respects_braces_inside_strings():
    raw = '{"reply": "use braces {like this} without breaking", "corrections": []}'
    obj = extract_json_object(raw, prefer_key="reply")
    assert obj is not None and "{like this}" in obj["reply"]


def test_revised_only_mode5():
    data = dict(CONTRACT)
    data["revised"] = "Sehr geehrte Frau Weber, ..."
    out = parse_teacher_reply(json.dumps(data, ensure_ascii=False))
    assert out["revised"].startswith("Sehr geehrte")


def test_correction_that_corrects_nothing_is_dropped():
    """The model sometimes means "this was already fine" but fills `corrections`
    with the same sentence in `original` and `corrected`. That drew a correction
    card over a correct sentence of the learner."""
    raw = json.dumps(
        {
            "reply": "Sehr gut!",
            "corrections": [
                {
                    "original": "Ich bin zwanzig Jahre alt.",
                    "corrected": "Ich bin zwanzig Jahre alt",
                    "note": "Perfect, nothing to correct.",
                },
                {
                    "original": "Meine Tochter hat sechs Jahre.",
                    "corrected": "Meine Tochter ist sechs Jahre alt.",
                    "note": "Age uses sein.",
                },
            ],
            "new_vocab": [],
            "suggested_followup": "",
        },
        ensure_ascii=False,
    )
    parsed = parse_teacher_reply(raw)
    assert len(parsed["corrections"]) == 1
    assert parsed["corrections"][0]["corrected"] == "Meine Tochter ist sechs Jahre alt."


def test_correction_quoting_something_not_said_is_dropped():
    """The model sometimes re-emits the previous turn's correction (it is in the
    history) or invents the `original`. The learner saw a correction of a
    sentence she never wrote."""
    said = "Ich bin zwanzig Jahre alt."
    cs = [
        {
            "original": "Meine Tochter hat sechs Jahre.",
            "corrected": "Meine Tochter ist sechs Jahre alt.",
            "note": "x",
        },
        {
            "original": "ich bin zwanzig jahre alt",
            "corrected": "Ich bin zwanzig Jahre alt.",
            "note": "y",
        },
        {"original": "", "corrected": "", "note": "loose note, kept"},
    ]
    out = drop_stale_corrections(cs, said)
    assert [c["note"] for c in out] == ["y", "loose note, kept"]


def test_partial_quote_of_what_was_said_is_kept():
    """Correcting part of the sentence is legitimate and frequent: the filter
    must not drop it."""
    cs = [{"original": "Ich habe gegangen", "corrected": "Ich bin gegangen", "note": "sein"}]
    said = "Gestern ich habe gegangen nach Hause mit meiner Kollegin."
    assert drop_stale_corrections(cs, said) == cs


def test_correction_that_only_appends_praise_is_not_a_correction():
    """The model "corrected" by returning the learner's good sentence with praise
    attached: 'Ich bin zwanzig. Sehr gut!' or '... (super!)'."""
    raw = json.dumps(
        {
            "reply": "Sehr gut!",
            "corrections": [
                {
                    "original": "Ich bin zwanzig Jahre alt.",
                    "corrected": "Ich bin zwanzig Jahre alt. Sehr gut!",
                    "note": "n",
                },
                {
                    "original": "Mein Sohn ist zehn Jahre alt.",
                    "corrected": "Mein Sohn ist zehn Jahre alt. (super! )",
                    "note": "n",
                },
            ],
            "new_vocab": [],
            "suggested_followup": "",
        },
        ensure_ascii=False,
    )
    assert parse_teacher_reply(raw)["corrections"] == []


def test_correction_that_adds_a_missing_word_is_kept():
    """Trimming praise must not destroy a legitimate correction that only ADDS
    something at the end."""
    raw = json.dumps(
        {
            "reply": "Genau.",
            "corrections": [
                {
                    "original": "Ich komme morgen",
                    "corrected": "Ich komme morgen nicht",
                    "note": "n",
                },
            ],
            "new_vocab": [],
            "suggested_followup": "",
        },
        ensure_ascii=False,
    )
    assert len(parse_teacher_reply(raw)["corrections"]) == 1


def test_quote_that_changes_the_word_in_error_is_dropped():
    """The most insidious case: the model quotes the learner's sentence changing
    exactly the word it then says is wrong, so it 'corrects' an error she never
    made."""
    cs = [
        {
            "original": "Mein Sohn hat zehn Jahre alt.",
            "corrected": "Mein Sohn ist zehn Jahre alt.",
            "note": "n",
        }
    ]
    assert drop_stale_corrections(cs, "Mein Sohn ist zehn Jahre alt.") == []
