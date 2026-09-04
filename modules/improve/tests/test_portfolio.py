"""Portfolio intelligence: what comparing the repositories actually yields."""

import pytest

from modules.improve.portfolio import (
    Technology,
    analyse,
    build_graph,
    dependency_divergence,
    normalise_specifier,
    travelling_recommendations,
)
from modules.improve.registry import parse_registry


def registry(*entries):
    return parse_registry({"repositories": list(entries)})


def entry(repo_id, tags=(), path=None):
    return {
        "id": repo_id,
        "name": repo_id.title(),
        "workspace": {"path": path or f"/srv/{repo_id}"},
        "tags": list(tags),
    }


def scan(languages=None, dependencies=None):
    return {
        "languages": languages or {},
        "dependencies": [
            {"name": name, "specifier": spec, "ecosystem": eco, "manifest": "m"}
            for name, spec, eco in (dependencies or [])
        ],
    }


# -- the graph -------------------------------------------------------------


def test_technologies_come_from_languages_dependencies_and_tags():
    repos = registry(entry("a", tags=["django"]))
    graph = build_graph(repos.all(), {"a": scan({"Python": 10}, [("psycopg", ">=3", "python")])})

    assert set(graph.technologies_of("a")) == {
        "tag:django",
        "language:python",
        "dependency:psycopg",
    }


def test_shared_technology_names_who_uses_it():
    repos = registry(entry("a"), entry("b"), entry("c"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("django", ">=5", "python")]),
            "b": scan(dependencies=[("django", ">=5", "python")]),
            "c": scan(dependencies=[("fastapi", ">=0.1", "python")]),
        },
    )

    assert graph.shared() == {"dependency:django": ["a", "b"]}
    assert graph.users_of("dependency:django") == ["a", "b"]


def test_ubiquitous_dependencies_say_nothing_by_being_shared():
    """Two repositories both using pytest is not portfolio intelligence."""
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("pytest", ">=8", "python")]),
            "b": scan(dependencies=[("pytest", ">=8", "python")]),
        },
    )

    assert graph.shared() == {}


def test_unique_technologies_are_identified():
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("pdfjs-dist", "^4", "npm")]),
            "b": scan(dependencies=[("alembic", ">=1", "python")]),
        },
    )

    assert graph.unique_to("a") == ["dependency:pdfjs-dist"]


def test_search_finds_partial_matches():
    repos = registry(entry("a", tags=["documents"]))
    graph = build_graph(repos.all(), {"a": scan(dependencies=[("pypdfium2", ">=4", "python")])})

    assert set(graph.search("pdf")) == {"dependency:pypdfium2"}


def test_an_unscanned_repository_still_contributes_its_tags():
    repos = registry(entry("a", tags=["security"]))
    graph = build_graph(repos.all(), {"a": None})

    assert graph.technologies_of("a") == ["tag:security"]


# -- version divergence ----------------------------------------------------


@pytest.mark.parametrize(
    "left,right",
    [
        (">=23.0,<24.0", ">=23,<24"),
        (">=6.7,<7.0", ">=6.7,<7"),
        ("^4.0.0", "^4"),
        (">=1, <2", "<2,>=1"),
    ],
)
def test_cosmetically_different_pins_are_the_same_pin(left, right):
    """Reporting these buries the divergences that are real."""
    assert normalise_specifier(left) == normalise_specifier(right)


def test_a_trailing_ten_is_not_a_trailing_zero():
    assert normalise_specifier(">=0.10") != normalise_specifier(">=0.1")


def test_a_genuine_difference_is_reported():
    divergence = dependency_divergence(
        {
            "a": scan(dependencies=[("nuxt", "^3.14.0", "npm")]),
            "b": scan(dependencies=[("nuxt", "^4.2.2", "npm")]),
        }
    )

    assert len(divergence) == 1
    assert divergence[0].name == "nuxt"
    assert divergence[0].specifiers == {"a": "^3.14.0", "b": "^4.2.2"}


def test_matching_pins_are_not_a_divergence():
    assert dependency_divergence(
        {
            "a": scan(dependencies=[("django", ">=5.2", "python")]),
            "b": scan(dependencies=[("django", ">=5.2", "python")]),
        }
    ) == []


def test_a_dependency_in_one_repository_is_not_a_divergence():
    assert dependency_divergence({"a": scan(dependencies=[("nuxt", "^4", "npm")])}) == []


def test_an_unpinned_dependency_diverges_from_a_pinned_one():
    divergence = dependency_divergence(
        {
            "a": scan(dependencies=[("pytest-asyncio", ">=0.24", "python")]),
            "b": scan(dependencies=[("pytest-asyncio", None, "python")]),
        }
    )

    assert "unpinned" in divergence[0].describe()


def test_the_report_shows_what_each_manifest_actually_says():
    """Compared normalised, reported verbatim."""
    divergence = dependency_divergence(
        {
            "a": scan(dependencies=[("psycopg", ">=3.2", "python")]),
            "b": scan(dependencies=[("psycopg", ">=3.2,<4", "python")]),
        }
    )

    assert ">=3.2,<4" in divergence[0].describe()


# -- travelling recommendations --------------------------------------------


def test_accepted_work_travels_to_repositories_sharing_technology():
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("django", ">=5", "python")]),
            "b": scan(dependencies=[("django", ">=5", "python")]),
        },
    )

    findings = travelling_recommendations(
        graph, {"a": [{"title": "Add OCR", "status": "accepted"}]}
    )

    assert len(findings) == 1
    assert findings[0].repositories == ["a", "b"]


def test_a_rejection_does_not_travel():
    """It is a judgement about one repository's circumstances."""
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("django", ">=5", "python")]),
            "b": scan(dependencies=[("django", ">=5", "python")]),
        },
    )

    assert travelling_recommendations(
        graph, {"a": [{"title": "Add OCR", "status": "rejected", "reason": "too early"}]}
    ) == []


def test_an_undecided_recommendation_does_not_travel():
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(repos.all(), {"a": scan(), "b": scan()})

    assert travelling_recommendations(
        graph, {"a": [{"title": "Add OCR", "status": "recommended"}]}
    ) == []


def test_nothing_travels_to_a_repository_with_nothing_in_common():
    repos = registry(entry("a"), entry("b"))
    graph = build_graph(
        repos.all(),
        {
            "a": scan(dependencies=[("django", ">=5", "python")]),
            "b": scan(dependencies=[("alembic", ">=1", "python")]),
        },
    )

    assert travelling_recommendations(
        graph, {"a": [{"title": "Add OCR", "status": "accepted"}]}
    ) == []


# -- the whole analysis ----------------------------------------------------


def test_analyse_returns_findings_for_divergence_and_travel():
    repos = registry(entry("a"), entry("b"))
    scans = {
        "a": scan(dependencies=[("django", ">=5.1", "python")]),
        "b": scan(dependencies=[("django", ">=5.2", "python")]),
    }
    result = analyse(repos.all(), scans, {"a": [{"title": "X", "status": "successful"}]})

    kinds = {finding.kind for finding in result["findings"]}
    assert kinds == {"version-divergence", "travelling-recommendation"}


def test_analyse_of_an_empty_portfolio_says_nothing():
    result = analyse([], {}, {})

    assert result["findings"] == []
    assert result["shared"] == {}
