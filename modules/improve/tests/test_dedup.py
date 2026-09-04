import math
import pytest

from modules.improve.recommend.dedup import (
    EMBEDDING_THRESHOLD,
    NEAR_EMBEDDING_THRESHOLD,
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


def _vector_at(angle: float) -> list:
    """A unit vector whose cosine against [1, 0] is cos(angle)."""
    return [math.cos(angle), math.sin(angle)]


def _prior_at(similarity: float, **kwargs) -> PriorRecommendation:
    fields = {
        "id": 2,
        "title": "Nuxt 4 is now the supported line",
        "normalized_title": "4 line now nuxt supported",
        "status": "accepted",
        "body": "Wholly different wording.",
    }
    fields.update(kwargs)
    return PriorRecommendation(
        embedding=pack_embedding(_vector_at(math.acos(similarity))), **fields
    )


def test_a_similarity_in_the_band_is_flagged_not_skipped():
    """0.83 is what the real pair scored: too close to ignore, too far to act.

    Skipping is silent, so acting on this would throw away a real idea with
    nobody seeing it.
    """
    prior = _prior_at(0.83)
    verdict = check("Nuxt 3 is in maintenance", "Body", [prior], embedding=[1.0, 0.0])

    assert not verdict.duplicate
    assert verdict.near
    assert verdict.reason is None, "a flag is not a skip"
    assert "#2" in verdict.near_reason
    assert "already accepted and awaiting implementation" in verdict.near_reason


def test_a_similarity_above_the_bar_is_still_skipped_outright():
    verdict = check("Whatever", "Body", [_prior_at(0.95)], embedding=[1.0, 0.0])

    assert verdict.duplicate
    assert not verdict.near, "a skip is not also a flag"


def test_a_similarity_below_the_band_is_left_alone():
    verdict = check("Whatever", "Body", [_prior_at(0.47)], embedding=[1.0, 0.0])

    assert not verdict.duplicate
    assert not verdict.near
    assert verdict.near_reason is None


@pytest.mark.parametrize(
    "similarity,flagged",
    [
        (0.79, False),
        # Not NEAR_EMBEDDING_THRESHOLD exactly: embeddings are packed as
        # float32, so 0.80 round-trips as 0.79999999 and lands on the wrong
        # side. The boundary is only meaningful to about 1e-7, which is fine
        # for a threshold picked by judgement, but not something to assert on.
        (NEAR_EMBEDDING_THRESHOLD + 1e-4, True),
        (0.89, True),
    ],
)
def test_the_band_edges(similarity, flagged):
    verdict = check("Whatever", "Body", [_prior_at(similarity)], embedding=[1.0, 0.0])
    assert verdict.near is flagged


def test_token_overlap_near_misses_are_not_flagged():
    """Only the semantic layer. Shared vocabulary is not a shared idea, and a
    flag that fires on it teaches the reviewer to skim past the flag."""
    prior = PriorRecommendation(
        id=3,
        title="Cache rendered cover mosaics on disk",
        normalized_title="cache cover disk mosaics rendered",
        status="rejected",
        body="Cache the rendered cover mosaics on disk to save work.",
    )
    verdict = check(
        "Cache rendered thumbnails in memory",
        "Cache the rendered thumbnails in memory to save work.",
        [prior],
    )

    assert not verdict.duplicate
    assert not verdict.near


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
