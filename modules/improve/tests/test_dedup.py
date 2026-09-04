import pytest

from modules.improve.recommend.dedup import (
    EMBEDDING_THRESHOLD,
    PriorRecommendation,
    check,
    cosine,
    pack_embedding,
    unpack_embedding,
)

REJECTED = PriorRecommendation(
    id=7,
    title="Semantic library search",
    normalized_title="library search semantic",
    status="rejected",
    reason="too much complexity for current product maturity",
    body="Embed every document and search the library by meaning.",
)


def test_nothing_is_a_duplicate_when_there_are_no_priors():
    assert not check("Anything", "Anything at all", []).duplicate


def test_a_reordered_title_is_caught():
    verdict = check("Library semantic search", "...", [REJECTED])
    assert verdict.duplicate
    assert verdict.method == "normalized title"


def test_the_verdict_says_what_is_outstanding():
    """The status matters more than the fact of duplication: "already accepted
    and waiting to be built" is a different thing to hear."""
    reason = check("Library semantic search", "...", [REJECTED]).reason

    assert "already rejected" in reason
    assert "product maturity" in reason


@pytest.mark.parametrize(
    "status,expected",
    [
        ("recommended", "awaiting your decision"),
        ("accepted", "awaiting implementation"),
        ("implemented", "already implemented"),
        ("awaiting review", "awaiting review"),
        ("abandoned", "then abandoned"),
    ],
)
def test_each_state_reads_as_what_is_outstanding(status, expected):
    prior = PriorRecommendation(
        id=7, title="Semantic library search",
        normalized_title="library search semantic", status=status, body="x",
    )
    assert expected in check("Library semantic search", "...", [prior]).reason


def test_a_reworded_title_is_caught_by_title_overlap():
    prior = PriorRecommendation(
        id=1,
        title="Local OCR for scanned PDF pages",
        normalized_title="local ocr pages pdf scanned",
        status="recommended",
        body="Run OCR in a background job.",
    )
    verdict = check(
        "Local OCR for scanned PDF documents",
        "Something entirely different in the body.",
        [prior],
    )
    assert verdict.duplicate


def test_an_unrelated_idea_is_not_a_duplicate():
    verdict = check(
        "Add a dark mode toggle",
        "Let readers switch to a dark palette at night.",
        [REJECTED],
    )
    assert not verdict.duplicate
    assert verdict.similarity < 0.3


def test_a_different_idea_sharing_vocabulary_is_not_a_duplicate():
    """Both are about searching documents; only one is the same proposal."""
    verdict = check(
        "Full-text search over PDFs",
        "Extract the text layer and index it for keyword search.",
        [REJECTED],
    )
    assert not verdict.duplicate


def test_a_near_miss_is_recorded_rather_than_discarded():
    """Below threshold but overlapping: the match is kept, the verdict is no."""
    verdict = check(
        "Semantic search across the library index",
        "Search documents by meaning.",
        [REJECTED],
    )
    assert verdict.matched is REJECTED
    assert not verdict.duplicate
    assert 0 < verdict.similarity < 1


def test_a_candidate_resembling_nothing_scores_zero_similarity():
    """Which is what makes its novelty score one."""
    verdict = check("Ship a physical keyboard", "Hardware.", [REJECTED])
    assert not verdict.duplicate
    assert verdict.similarity == 0.0


def test_an_embedding_match_above_threshold_is_a_duplicate():
    vector = [1.0, 0.0, 0.0]
    prior = PriorRecommendation(
        id=2,
        title="Completely different words",
        normalized_title="completely different words",
        status="recommended",
        body="Nothing in common textually.",
        embedding=pack_embedding(vector),
    )
    verdict = check("Unrelated phrasing", "Unrelated body", [prior], embedding=vector)

    assert verdict.duplicate
    assert verdict.method == "embedding"
    assert verdict.similarity >= EMBEDDING_THRESHOLD


def test_a_distant_embedding_is_not_a_duplicate():
    prior = PriorRecommendation(
        id=2,
        title="X",
        normalized_title="x",
        status="recommended",
        embedding=pack_embedding([1.0, 0.0]),
    )
    assert not check("Y", "Y", [prior], embedding=[0.0, 1.0]).duplicate


def test_embeddings_round_trip():
    vector = [0.5, -0.25, 1.0]
    restored = unpack_embedding(pack_embedding(vector))
    assert all(abs(a - b) < 1e-6 for a, b in zip(vector, restored))


def test_cosine_handles_degenerate_input():
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine([1.0, 2.0], [1.0]) == 0.0


def test_dedup_still_works_with_no_embeddings_available():
    """The usual state of a LM Studio set up for chat."""
    verdict = check("Library semantic search", "...", [REJECTED], embedding=None)
    assert verdict.duplicate
