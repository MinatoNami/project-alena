"""Scanner tests, against a real git repository."""

import pytest

from modules.improve.scan import (
    GitError,
    GitRepository,
    MARKERS,
    detect_languages,
    diff_todos,
    extract_dependencies,
    fingerprint,
    has_changed,
    parse_grep,
)

from .conftest import git


# -- git -------------------------------------------------------------------


def test_state_reads_head_branch_and_files(repo):
    state = GitRepository(repo).state()

    assert state.branch == "main"
    assert state.head_sha
    assert set(state.tracked_files) == {"README.md", "requirements.txt", "app.py"}
    assert state.recent_commits[0].subject == "Initial commit"
    assert not state.dirty


def test_uncommitted_work_makes_the_tree_dirty(repo):
    (repo / "app.py").write_text("changed\n")
    state = GitRepository(repo).state()

    assert state.dirty
    assert state.dirty_files == ["app.py"]


def test_a_directory_that_is_not_a_repository_is_an_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitError, match="not a git repository"):
        GitRepository(plain).state()


def test_an_empty_repository_has_no_head(tmp_path):
    """A fresh `git init` is a valid state, not a failure."""
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")

    state = GitRepository(empty).state()
    assert state.head_sha is None
    assert state.tracked_files == []


def test_diff_is_truncated_for_a_model_context(repo):
    first = GitRepository(repo).head_sha()
    (repo / "big.txt").write_text("x" * 50_000)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Add a big file")

    diff = GitRepository(repo).diff(first, max_chars=1000)
    assert len(diff) < 1200
    assert "truncated" in diff


def test_grep_only_covers_tracked_files(repo):
    (repo / "untracked.py").write_text("# TODO: not tracked\n")
    hits = GitRepository(repo).grep(MARKERS)

    assert any("app.py" in hit for hit in hits)
    assert not any("untracked.py" in hit for hit in hits)


# -- fingerprint -----------------------------------------------------------


def test_fingerprint_is_stable_when_nothing_happens(repo):
    git_repo = GitRepository(repo)
    assert fingerprint(git_repo.state()) == fingerprint(git_repo.state())


def test_fingerprint_changes_on_a_commit(repo):
    before = fingerprint(GitRepository(repo).state())
    (repo / "new.py").write_text("print('new')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Add a file")

    assert fingerprint(GitRepository(repo).state()) != before


def test_fingerprint_changes_on_uncommitted_work(repo):
    """A repository sitting on dirty work has moved even though HEAD has not."""
    before = fingerprint(GitRepository(repo).state())
    (repo / "app.py").write_text("changed\n")

    assert fingerprint(GitRepository(repo).state()) != before


def test_a_repository_with_no_previous_scan_counts_as_changed():
    assert has_changed("abc", None)
    assert not has_changed("abc", "abc")


# -- dependencies ----------------------------------------------------------


def test_requirements_are_parsed_with_their_specifiers(repo):
    found = {d.name: d for d in extract_dependencies(repo, ["requirements.txt"])}

    assert found["httpx"].specifier == ">=0.27"
    assert found["fastapi"].specifier is None
    assert "#" not in found


def test_package_json_covers_both_dependency_sections(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"vue": "^3"}, "devDependencies": {"eslint": "^9"}}'
    )
    names = {d.name for d in extract_dependencies(tmp_path, ["package.json"])}

    assert names == {"vue", "eslint"}


def test_pyproject_dependencies_are_parsed(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["httpx>=0.27", "rich"]\n'
    )
    names = {d.name for d in extract_dependencies(tmp_path, ["pyproject.toml"])}

    assert names == {"httpx", "rich"}


def test_a_malformed_manifest_does_not_fail_the_scan(tmp_path):
    (tmp_path / "package.json").write_text("{not json")
    assert extract_dependencies(tmp_path, ["package.json"]) == []


def test_a_dependency_in_two_manifests_is_one_dependency(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["httpx"]\n'
    )
    found = extract_dependencies(tmp_path, ["requirements.txt", "pyproject.toml"])

    assert [d.name for d in found] == ["httpx"]


def test_only_tracked_manifests_are_read(tmp_path):
    """A vendored package.json under node_modules is not a project dependency."""
    vendored = tmp_path / "node_modules" / "left-pad"
    vendored.mkdir(parents=True)
    (vendored / "package.json").write_text('{"dependencies": {"sneaky": "1"}}')

    assert extract_dependencies(tmp_path, []) == []


def test_languages_are_counted_most_common_first():
    counts = detect_languages(["a.py", "b.py", "c.ts", "d.unknown"])
    assert list(counts) == ["Python", "TypeScript"]
    assert counts["Python"] == 2


# -- todos -----------------------------------------------------------------


def test_grep_output_is_parsed_into_todos():
    todos = parse_grep(["app.py:12:    # TODO: wire up the router"])

    assert todos[0].path == "app.py"
    assert todos[0].line == 12
    assert todos[0].marker == "TODO"
    assert todos[0].text == "wire up the router"


def test_lines_without_a_marker_are_ignored():
    assert parse_grep(["app.py:1:print('hello')"]) == []


def test_the_diff_reports_what_appeared_and_what_went_away():
    previous = [{"path": "a.py", "line": 1, "marker": "TODO", "text": "old"}]
    current = parse_grep(["b.py:2:# TODO: new"])

    delta = diff_todos(current, previous)

    assert [t["text"] for t in delta["added"]] == ["new"]
    assert [t["text"] for t in delta["resolved"]] == ["old"]


def test_a_todo_that_only_moved_is_not_reported_as_churn():
    """Otherwise every edit above a TODO shows up as resolved-and-reintroduced."""
    previous = [{"path": "a.py", "line": 10, "marker": "TODO", "text": "same"}]
    current = parse_grep(["a.py:42:# TODO: same"])

    delta = diff_todos(current, previous)

    assert delta["added"] == []
    assert delta["resolved"] == []
