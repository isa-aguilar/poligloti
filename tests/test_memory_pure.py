"""Tests for the pure functions of memory.py (no disk access)."""

from backend.memory import _tail, normalize_vocab_term, parse_frontmatter, slugify
from backend.ocr import clean_page_text


def test_slugify_basic_and_accents():
    assert slugify("Café Meeting — Qualité & Crème") == "cafe-meeting-qualite-creme"
    assert slugify("") == "untitled"
    assert slugify("!!!") == "untitled"


def test_slugify_respects_max_len_without_trailing_dash():
    out = slugify("a" * 50, max_len=10)
    assert len(out) <= 10 and not out.endswith("-")


def test_normalize_vocab_term_strips_article():
    assert normalize_vocab_term("die Bordkarte") == "bordkarte"
    assert normalize_vocab_term("The Ticket") == "ticket"
    assert normalize_vocab_term("Bordkarte") == "bordkarte"
    # Only the leading article, not words inside the term.
    assert normalize_vocab_term("mitten in der Nacht") == "mitten in der nacht"


def test_tail_ignores_blank_lines():
    text = "one\n\n\ntwo\nthree\n\n"
    assert _tail(text, 2) == "two\nthree"
    assert _tail(text, 10) == "one\ntwo\nthree"


def test_parse_frontmatter_values_and_lists():
    text = "---\ncefr: A2-B1\nlanguages_studied: [de, en]\n# ignored comment\n---\nbody"
    data = parse_frontmatter(text)
    assert data["cefr"] == "A2-B1"
    assert data["languages_studied"] == ["de", "en"]


def test_parse_frontmatter_without_frontmatter():
    assert parse_frontmatter("body only") == {}
    assert parse_frontmatter("---\nnot closed") == {}


# --- OCR: post-processing of a page's text (book mode) ----------------------


def test_clean_page_text_joins_hyphens_and_drops_page_numbers():
    raw = (
        "Jonas stellte zwei Tassen auf den Tisch. »Ich räu-\nme gleich die Küche auf.«"
        "\n\n82\n\nDann ging er zum Fenster und schaute hinaus."
    )
    out = clean_page_text(raw)
    assert "räume" in out
    assert "82" not in out
    assert out.count("\n\n") == 1  # two paragraphs


def test_clean_page_text_collapses_paragraph_lines():
    raw = "Erste Zeile\nzweite Zeile\ndritte Zeile."
    assert clean_page_text(raw) == "Erste Zeile zweite Zeile dritte Zeile."
