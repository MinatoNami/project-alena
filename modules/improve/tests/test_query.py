"""The read-only queries the MCP server exposes.

Two of these exist because of a specific failure. ALENA's research agent
searched for FIXME, got three hits that were all prose or string literals, and
could not open a single file to check whether what it was proposing already
existed. Codex rejected all three by reading the code. `context` and
`read_repository_file` are what close that gap.
"""

import pytest

from modules.improve.query import read_repository_file, search_repository
from modules.improve.registry import RegistryError


def test_search_returns_the_matching_line(registry):
    hits = search_repository("sample", "TODO", registry=registry)

    assert [hit["path"] for hit in hits] == ["app.py"]


def test_search_can_return_the_lines_around_a_hit(registry):
    """A bare matching line cannot tell a comment from a string literal."""
    hits = search_repository("sample", "TODO", registry=registry, context=2)

    assert "context" in hits[0]
    lines = {line["line"] for line in hits[0]["context"]}
    assert hits[0]["line"] in lines, "the hit itself is in its own context"
    assert len(lines) > 1, "and so is what surrounds it"


def test_no_context_is_asked_for_by_default(registry):
    """Context is not free -- a screenful per hit fills the window with one
    search -- so a caller opts in."""
    hits = search_repository("sample", "TODO", registry=registry)

    assert "context" not in hits[0]


def test_context_is_capped(registry):
    """A caller asking for a thousand lines either side gets ten."""
    hits = search_repository("sample", "TODO", registry=registry, context=1000)

    assert len(hits[0]["context"]) <= 21


def test_search_can_exclude_a_path(registry):
    everywhere = search_repository("sample", "TODO", registry=registry)
    excluded = search_repository(
        "sample", "TODO", registry=registry, exclude="*.py"
    )

    assert everywhere and not excluded


# -- reading ---------------------------------------------------------------


def test_a_tracked_file_can_be_read(registry):
    result = read_repository_file("sample", "app.py", registry=registry)

    assert result["path"] == "app.py"
    assert "wire up the router" in result["text"]
    assert result["truncated"] is False


def test_reading_can_be_windowed(registry):
    result = read_repository_file(
        "sample", "app.py", start=2, limit=1, registry=registry
    )

    assert result["returned"] == 1
    assert result["start"] == 2
    assert "TODO" not in result["text"], "the window skipped the first line"


def test_a_short_read_says_there_is_more(registry):
    result = read_repository_file("sample", "app.py", limit=1, registry=registry)

    assert result["truncated"] is True
    assert result["lines"] > result["returned"]


def test_a_path_outside_the_workspace_is_refused(registry):
    """The one thing a read tool must not allow. alena-core is reached
    directly, with no gateway in the path, so this check is the boundary."""
    with pytest.raises(RegistryError, match="outside"):
        read_repository_file("sample", "../../../etc/passwd", registry=registry)


def test_an_absolute_path_elsewhere_is_refused(registry):
    with pytest.raises(RegistryError, match="outside"):
        read_repository_file("sample", "/etc/passwd", registry=registry)


def test_an_untracked_file_is_refused(registry, repo):
    """`git ls-files` is the allowlist, so a secret nobody committed stays
    unreadable -- without a denylist of secret names to keep current."""
    (repo / ".env").write_text("TOKEN=hunter2\n")

    with pytest.raises(RegistryError, match="not a tracked file"):
        read_repository_file("sample", ".env", registry=registry)


def test_an_empty_path_is_refused(registry):
    with pytest.raises(RegistryError):
        read_repository_file("sample", "   ", registry=registry)
