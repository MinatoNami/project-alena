import pytest

from modules.improve.recommend.scoring import (
    DEFAULT_WEIGHTS,
    Dimensions,
    effort_for,
    evidence_score,
    novelty_score,
    priority_for,
    score,
)


def test_the_weights_are_the_ones_in_the_spec():
    assert DEFAULT_WEIGHTS == {
        "value": 0.30,
        "fit": 0.20,
        "evidence": 0.15,
        "novelty": 0.15,
        "confidence": 0.10,
        "cost": -0.05,
        "risk": -0.05,
    }


def test_the_best_possible_candidate_normalises_to_one():
    result = score(Dimensions(value=1, fit=1, evidence=1, novelty=1, confidence=1, cost=0, risk=0))
    assert result.raw == pytest.approx(0.90)
    assert result.normalized == pytest.approx(1.0)
    assert result.priority == "HIGH"


def test_the_worst_possible_candidate_normalises_to_zero():
    result = score(Dimensions(value=0, fit=0, evidence=0, novelty=0, confidence=0, cost=1, risk=1))
    assert result.raw == pytest.approx(-0.10)
    assert result.normalized == pytest.approx(0.0)
    assert result.priority == "LOW"


def test_cost_and_risk_subtract():
    without = score(Dimensions(cost=0, risk=0))
    with_penalty = score(Dimensions(cost=1, risk=1))
    assert with_penalty.raw < without.raw


def test_a_missing_dimension_lands_mid_table_not_at_the_bottom():
    """A failed review should reach a human, not sink out of sight."""
    assert score(Dimensions.from_mapping({})).priority == "MEDIUM"


def test_out_of_range_values_are_clamped():
    dimensions = Dimensions.from_mapping({"value": 9.0, "risk": -4.0})
    assert dimensions.value == 1.0
    assert dimensions.risk == 0.0


def test_nonsense_values_fall_back_to_neutral():
    assert Dimensions.from_mapping({"value": "very high"}).value == 0.5


def test_weights_can_be_replaced_without_touching_the_calculation():
    """The spec says these should eventually be fitted to acceptance history."""
    only_value = {"value": 1.0}
    assert score(Dimensions(value=1.0), only_value).normalized == pytest.approx(1.0)


@pytest.mark.parametrize(
    "normalized,expected",
    [(0.95, "HIGH"), (0.70, "HIGH"), (0.69, "MEDIUM"), (0.45, "MEDIUM"), (0.44, "LOW")],
)
def test_priority_bands(normalized, expected):
    assert priority_for(normalized) == expected


@pytest.mark.parametrize(
    "cost,expected", [(0.0, "SMALL"), (0.33, "SMALL"), (0.5, "MEDIUM"), (0.9, "LARGE")]
)
def test_effort_bands(cost, expected):
    assert effort_for(cost) == expected


@pytest.mark.parametrize(
    "evidence,expected",
    [
        (None, 0.0),
        ("", 0.0),
        ("the vendor said so", 0.3),
        ("https://a", 0.6),
        ("https://a https://b", 0.8),
        ("https://a https://b https://c", 1.0),
    ],
)
def test_evidence_counts_citations(evidence, expected):
    assert evidence_score(evidence) == expected


def test_novelty_is_the_inverse_of_similarity():
    assert novelty_score(0.0) == 1.0
    assert novelty_score(1.0) == 0.0
    assert novelty_score(0.25) == pytest.approx(0.75)
