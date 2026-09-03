"""The action agent: the only thing in ALENA that writes to a repository.

Against a real git repository, because what is being checked is which branch
things land on and what the working tree looks like afterwards.
"""

import asyncio
from pathlib import Path

import pytest

from modules.gateway import get_gateway, set_gateway
from modules.gateway.contracts import SideEffect
from modules.improve.action.implement import AGENT, branch_name, implement_async
from modules.improve.action.routing import RoutingError, pair_for
from modules.improve.action.verify import TestResult, detect_test_command, run_tests
from modules.improve.decide import ACCEPTED, decide
from modules.improve.persistence import (
    implementations_for,
    record_observation,
    record_research,
    upsert_recommendation,
    upsert_repository,
)
from modules.improve.registry import RegistryError, parse_registry
from modules.improve.scan import GitRepository
from modules.improve.wiring import install_gateway

from .conftest import git


@pytest.fixture
def writable(repo, tmp_path):
    """The sample repository, with write capabilities declared."""
    registry = parse_registry(
        {
            "repositories": [
                {
                    "id": "sample",
                    "name": "Sample",
                    "workspace": {"path": str(repo)},
                    "capabilities": {"modify": True, "create_branch": True},
                }
            ]
        }
    )
    install_gateway(registry)
    yield registry.resolve("sample", "modify")
    set_gateway(None)


@pytest.fixture
def accepted(writable):
    upsert_repository(writable)
    research_id, _ = record_research(
        repository_id=writable.id, source="test", content="# R", content_hash="h"
    )
    observation_id = record_observation(
        research_id=research_id,
        repository_id=writable.id,
        title="Add a farewell function",
        normalized_title="add farewell function",
        body="Callers want a goodbye as well as a hello.",
        evidence=None,
    )
    recommendation_id = upsert_recommendation(
        repository_id=writable.id,
        observation_id=observation_id,
        title="Add a farewell function",
        normalized_title="add farewell function",
        body="Callers want a goodbye as well as a hello.",
        score=0.8,
    )
    decide(writable.id, recommendation_id, ACCEPTED)
    return recommendation_id


def writer(filename="new_module.py", content="VALUE = 1\n"):
    """Stands in for codex_edit, writing a file the way it would."""

    async def executor(server, tool, arguments, **kwargs):
        assert tool == "codex_edit"
        assert kwargs["agent"] == AGENT
        (Path(arguments["repo_path"]) / filename).write_text(content)
        return type("Result", (), {"content": []})()

    return executor


def approving(prompt, **kwargs):
    return '```json\n{"verdict": "supported"}\n```'


def run(repository, recommendation_id, **kwargs):
    kwargs.setdefault("executor", writer())
    kwargs.setdefault("review_caller", approving)
    kwargs.setdefault("run_tests_enabled", False)
    return asyncio.run(implement_async(repository, recommendation_id, **kwargs))


# -- branch naming ---------------------------------------------------------


def test_a_branch_is_named_after_the_recommendation():
    assert branch_name(3, "Semantic library search") == "alena/3-semantic-library-search"


def test_a_hostile_title_cannot_shape_the_branch_name():
    """The title carries research text; it becomes a git argument."""
    name = branch_name(1, "x; rm -rf / --upload-pack=touch#$(whoami)")
    assert set(name) <= set("abcdefghijklmnopqrstuvwxyz0123456789-/")


def test_a_title_of_only_punctuation_still_yields_a_branch():
    assert branch_name(9, "!!!") == "alena/9-change"


# -- the gates -------------------------------------------------------------


def test_a_repository_that_forbids_modification_is_refused(repo):
    registry = parse_registry(
        {"repositories": [{"id": "sample", "workspace": {"path": str(repo)}}]}
    )
    with pytest.raises(RegistryError, match="modify"):
        run(registry.resolve("sample"), 1)


def test_an_unaccepted_recommendation_is_refused(writable, accepted):
    from modules.improve.decide import REJECTED, decide as record

    record(writable.id, accepted, REJECTED, reason="not now")
    outcome = run(writable, accepted)

    assert not outcome.ok
    assert "not accepted" in outcome.error


def test_a_dirty_workspace_is_refused_and_lists_why(repo, writable, accepted):
    (repo / "app.py").write_text("someone was working here\n")

    outcome = run(writable, accepted)

    assert not outcome.ok
    assert "app.py" in outcome.error


def test_an_untracked_file_also_blocks(repo, writable, accepted):
    """The commit stages everything, on the strength of this check."""
    (repo / "scratch.txt").write_text("notes\n")

    assert not run(writable, accepted).ok


# -- the happy path --------------------------------------------------------


def test_the_change_lands_on_a_new_branch(repo, writable, accepted):
    outcome = run(writable, accepted)

    assert outcome.ok
    assert outcome.branch.startswith("alena/")
    assert outcome.base_branch == "main"
    assert outcome.files_changed == ["new_module.py"]


def test_the_default_branch_is_never_committed_to(repo, writable, accepted):
    """The one irreversible mistake available here."""
    before = GitRepository(repo).head_sha()

    run(writable, accepted)

    assert GitRepository(repo).head_sha() == before, "main moved"


def test_the_workspace_is_left_on_the_branch_it_started_on(repo, writable, accepted):
    run(writable, accepted)

    assert GitRepository(repo).branch() == "main"


def test_the_branch_survives_for_a_human_to_look_at(repo, writable, accepted):
    outcome = run(writable, accepted)

    branches = git(repo, "branch", "--list")
    assert outcome.branch in branches


def test_the_commit_references_the_recommendation(repo, writable, accepted):
    outcome = run(writable, accepted)

    message = git(repo, "log", "-1", "--format=%B", outcome.branch)
    assert f"recommendation #{accepted}" in message
    assert "reviewed by claude" in message


def test_nothing_is_pushed(repo, writable, accepted):
    """Pushing is a separate act with its own approval; it is not implemented."""
    outcome = run(writable, accepted)

    assert implementations_for(accepted)[0]["pushed"] == 0
    assert implementations_for(accepted)[0]["pull_request_url"] is None


# -- the grant -------------------------------------------------------------


def test_the_grant_is_live_only_while_the_agent_writes(repo, writable, accepted):
    seen = {}

    async def checking(server, tool, arguments, **kwargs):
        seen["during"] = bool(
            get_gateway().grants.find(AGENT, "sample", SideEffect.REPOSITORY_WRITE)
        )
        (Path(arguments["repo_path"]) / "f.py").write_text("x = 1\n")
        return type("Result", (), {"content": []})()

    run(writable, accepted, executor=checking)

    assert seen["during"]
    assert get_gateway().grants.grants == []


def test_the_grant_is_dropped_when_the_agent_fails(repo, writable, accepted):
    async def exploding(server, tool, arguments, **kwargs):
        raise RuntimeError("codex fell over")

    outcome = run(writable, accepted, executor=exploding)

    assert not outcome.ok
    assert get_gateway().grants.grants == []


# -- failure leaves nothing behind ------------------------------------------


def test_a_failed_run_restores_the_workspace(repo, writable, accepted):
    async def exploding(server, tool, arguments, **kwargs):
        (Path(arguments["repo_path"]) / "half.py").write_text("incomplete\n")
        raise RuntimeError("codex fell over")

    run(writable, accepted, executor=exploding)

    assert GitRepository(repo).branch() == "main"
    assert not GitRepository(repo).dirty_files()


def test_a_failed_run_deletes_its_branch(repo, writable, accepted):
    async def exploding(server, tool, arguments, **kwargs):
        raise RuntimeError("codex fell over")

    outcome = run(writable, accepted, executor=exploding)

    assert outcome.branch not in git(repo, "branch", "--list")


def test_an_agent_that_changes_nothing_is_a_failure(repo, writable, accepted):
    async def lazy(server, tool, arguments, **kwargs):
        return type("Result", (), {"content": []})()

    outcome = run(writable, accepted, executor=lazy)

    assert not outcome.ok
    assert "changed nothing" in outcome.error


def test_a_failure_is_recorded_with_its_branch(repo, writable, accepted):
    async def exploding(server, tool, arguments, **kwargs):
        raise RuntimeError("codex fell over")

    run(writable, accepted, executor=exploding)

    row = implementations_for(accepted)[0]
    assert row["status"] == "failed"
    assert row["branch"]  # so a half-finished branch can be found


# -- cross review ----------------------------------------------------------


def test_the_reviewer_is_not_the_implementer(repo, writable, accepted):
    outcome = run(writable, accepted)

    assert outcome.pairing.implementer != outcome.pairing.reviewer
    assert outcome.review.agent == outcome.pairing.reviewer


def test_the_reviewer_is_shown_the_diff(repo, writable, accepted):
    seen = {}

    def capture(prompt, **kwargs):
        seen["prompt"] = prompt
        return '{"verdict": "supported"}'

    run(writable, accepted, review_caller=capture)

    assert "```diff" in seen["prompt"]
    assert "new_module.py" in seen["prompt"]


def test_a_failed_review_does_not_undo_the_branch(repo, writable, accepted):
    """The work is still there for a human even if nobody could review it."""

    def failing(prompt, **kwargs):
        raise RuntimeError("routine unreachable")

    outcome = run(writable, accepted, review_caller=failing)

    assert outcome.ok
    assert outcome.branch in git(repo, "branch", "--list")
    assert outcome.review.verdict == "error"


def test_routing_refuses_an_agent_that_cannot_write_locally():
    with pytest.raises(RoutingError, match="cannot write"):
        pair_for("claude")


def test_routing_refuses_to_let_a_model_review_itself():
    with pytest.raises(RoutingError, match="not an independent check"):
        pair_for("codex", available_reviewers=("codex",))


# -- test detection --------------------------------------------------------


def test_a_python_project_is_detected(repo):
    (repo / "conftest.py").write_text("")
    assert detect_test_command(repo, ["conftest.py", "app.py"]) == "pytest -q"


def test_a_node_project_with_a_test_script_is_detected(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    assert detect_test_command(tmp_path, ["package.json"]) == "npm test --silent"


def test_a_node_project_without_a_test_script_is_not():
    assert detect_test_command(Path("."), []) is None


def test_an_unrecognised_project_reports_no_command(tmp_path):
    """Claiming tests passed when none ran is the worst possible answer."""
    assert detect_test_command(tmp_path, ["main.rb"]) is None


def test_a_missing_runner_is_reported_rather_than_swallowed(tmp_path):
    result = run_tests(tmp_path, "definitely-not-a-real-runner --version")

    assert not result.ran
    assert "not found" in result.describe()


def test_no_command_means_not_run():
    assert not TestResult(None, None, "no test command detected").ran


# -- build artifacts -------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "__pycache__/",
        "src/__pycache__/app.cpython-314.pyc",
        ".pytest_cache/v/cache",
        "node_modules/left-pad/index.js",
        "app.pyc",
        "src/mypackage.egg-info/PKG-INFO",
        ".DS_Store",
    ],
)
def test_build_artifacts_are_recognised(path):
    from modules.improve.action.implement import is_generated_artifact

    assert is_generated_artifact(path)


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "docs/pycache_notes.md", "src/egg-info-guide.md", "tests/test_x.py"],
)
def test_real_files_are_not_mistaken_for_artifacts(path):
    from modules.improve.action.implement import is_generated_artifact

    assert not is_generated_artifact(path)


def test_artifacts_the_agent_leaves_behind_are_not_committed(repo, writable, accepted):
    """The implementing agent runs the tests while it works; a branch destined
    for review should not carry byte-compiled caches."""

    async def messy(server, tool, arguments, **kwargs):
        workspace = Path(arguments["repo_path"])
        (workspace / "feature.py").write_text("VALUE = 1\n")
        cache = workspace / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "feature.cpython-314.pyc").write_bytes(b"\x00compiled")
        return type("Result", (), {"content": []})()

    outcome = run(writable, accepted, executor=messy)

    assert outcome.files_changed == ["feature.py"]
    committed = git(repo, "show", "--name-only", "--format=", outcome.branch)
    assert "__pycache__" not in committed


def test_a_run_that_only_produced_artifacts_counts_as_no_change(repo, writable, accepted):
    async def only_cache(server, tool, arguments, **kwargs):
        cache = Path(arguments["repo_path"]) / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "x.pyc").write_bytes(b"\x00")
        return type("Result", (), {"content": []})()

    outcome = run(writable, accepted, executor=only_cache)

    assert not outcome.ok
    assert "changed nothing" in outcome.error


# -- finding tests in a monorepo -------------------------------------------


@pytest.fixture
def monorepo(tmp_path):
    """LumaIndex's shape: manifests in subdirectories, nothing at the root."""
    workspace = tmp_path / "mono"
    (workspace / "frontend").mkdir(parents=True)
    (workspace / "backend").mkdir(parents=True)
    (workspace / "frontend" / "package.json").write_text(
        '{"scripts": {"test": "vitest run", "build": "nuxt build"}}'
    )
    (workspace / "backend" / "pytest.ini").write_text("[pytest]\n")
    return workspace, [
        "README.md",
        "frontend/package.json",
        "frontend/nuxt.config.ts",
        "backend/pytest.ini",
        "backend/app.py",
    ]


def test_manifests_in_subdirectories_are_found(monorepo):
    """Looking only at the root found neither, so a change went to review with
    its tests never run -- which reads as "there were no tests"."""
    from modules.improve.action.verify import detect_test_suites

    workspace, tracked = monorepo
    assert detect_test_suites(workspace, tracked) == [
        ("pytest -q", "backend"),
        ("npm test --silent", "frontend"),
    ]


def test_only_the_suites_the_change_touches_are_run(monorepo):
    from modules.improve.action.verify import detect_test_suites

    workspace, tracked = monorepo
    assert detect_test_suites(workspace, tracked, ["frontend/nuxt.config.ts"]) == [
        ("npm test --silent", "frontend")
    ]


def test_a_change_spanning_both_runs_both(monorepo):
    from modules.improve.action.verify import detect_test_suites

    workspace, tracked = monorepo
    suites = detect_test_suites(
        workspace, tracked, ["frontend/nuxt.config.ts", "backend/app.py"]
    )
    assert len(suites) == 2


def test_a_change_owned_by_no_project_runs_nothing(monorepo):
    from modules.improve.action.verify import detect_test_suites

    workspace, tracked = monorepo
    assert detect_test_suites(workspace, tracked, ["README.md"]) == []


def test_a_package_without_a_test_script_is_not_a_suite(tmp_path):
    from modules.improve.action.verify import detect_test_suites

    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text('{"scripts": {"build": "vite"}}')

    assert detect_test_suites(tmp_path, ["web/package.json"]) == []


def test_a_nested_change_finds_its_nearest_manifest(monorepo):
    from modules.improve.action.verify import detect_test_suites

    workspace, tracked = monorepo
    suites = detect_test_suites(
        workspace, tracked, ["frontend/components/deep/Thing.vue"]
    )
    assert suites == [("npm test --silent", "frontend")]


def test_one_failing_suite_fails_the_run(monorepo, monkeypatch):
    from modules.improve.action import implement as implement_module
    from modules.improve.action.verify import TestResult

    workspace, _ = monorepo
    results = iter(
        [
            TestResult("pytest -q", True, "ok", "backend"),
            TestResult("npm test --silent", False, "boom", "frontend"),
        ]
    )
    monkeypatch.setattr(
        implement_module, "run_tests", lambda *a, **k: next(results)
    )

    combined = implement_module._run_suites(
        workspace, [("pytest -q", "backend"), ("npm test --silent", "frontend")]
    )
    assert combined.passed is False
    assert "boom" in combined.output


def test_the_directory_appears_in_the_description():
    from modules.improve.action.verify import TestResult

    assert "frontend" in TestResult("npm test", True, "", "frontend").describe()
