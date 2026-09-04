from modules.improve.research import parse_research
from modules.improve.text import normalize_title

DOC = """# Research: luma-index

Repository: luma-index
Date: 2026-09-03
Source: chatgpt-work

## Local OCR is practical now

OCR models run on consumer hardware.

**Evidence:** https://a.example https://b.example

## Empty heading

## EPUB is the top request

Readers want EPUB.
"""


def test_header_fields_are_read():
    parsed = parse_research(DOC)
    assert parsed.title == "Research: luma-index"
    assert parsed.source == "chatgpt-work"
    assert parsed.document_date == "2026-09-03"
    assert parsed.repository == "luma-index"


def test_each_heading_is_one_observation():
    titles = [o.title for o in parse_research(DOC).observations]
    assert titles == ["Local OCR is practical now", "EPUB is the top request"]


def test_a_heading_with_nothing_under_it_is_not_an_observation():
    """It is a table of contents entry, not a claim."""
    assert "Empty heading" not in [o.title for o in parse_research(DOC).observations]


def test_evidence_is_separated_from_the_body():
    first = parse_research(DOC).observations[0]
    assert first.evidence == "https://a.example https://b.example"
    assert "Evidence" not in first.body


def test_emphasis_around_a_field_is_tolerated():
    for variant in ("**Evidence:** x", "**Evidence**: x", "Evidence: x", "_Evidence_: x"):
        doc = f"# R\n\n## T\n\nbody\n\n{variant}\n"
        assert parse_research(doc).observations[0].evidence == "x"


def test_a_document_with_no_headings_is_still_ingested():
    """A research report in the wrong shape is still worth reading."""
    parsed = parse_research("# Weekly research\n\nSomething happened.\n")
    assert len(parsed.observations) == 1
    assert "Something happened." in parsed.observations[0].body


def test_the_content_hash_is_stable():
    assert parse_research(DOC).content_hash == parse_research(DOC).content_hash


def test_reworded_titles_normalise_to_the_same_string():
    assert normalize_title("Semantic search for the library") == normalize_title(
        "Library semantic search"
    )


def test_stopwords_do_not_change_a_title():
    assert normalize_title("Local OCR for scanned PDFs has become practical") == (
        normalize_title("Practical local OCR for scanned PDFs")
    )


def test_a_title_of_only_stopwords_keeps_its_words():
    """Dropping everything would make every such title identical."""
    assert normalize_title("It is what it is") != ""
