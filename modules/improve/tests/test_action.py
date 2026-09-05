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


def test_a_second_attempt_gets_its_own_branch():
    """Before this, every retry died on the branch it was retrying."""
    from modules.improve.action.implement import free_branch_name

    first = branch_name(2, "Nuxt 4 is the supported line")

    assert free_branch_name(2, "Nuxt 4 is the supported line", []) == first
    assert (
        free_branch_name(2, "Nuxt 4 is the supported line", [first])
        == f"{first}-attempt-2"
    )
    assert (
        free_branch_name(2, "Nuxt 4 is the supported line", [first, f"{first}-attempt-2"])
        == f"{first}-attempt-3"
    )


def test_an_earlier_attempt_is_left_alone(repo, writable, accepted):
    """It holds a real commit; a retry does not get to decide it is rubbish."""
    first = run(writable, accepted)

    from modules.improve.decide import ACCEPTED as A, UNSUCCESSFUL, decide as record

    record(writable.id, accepted, UNSUCCESSFUL, reason="tests failed")
    record(writable.id, accepted, A)
    second = run(writable, accepted)

    assert second.ok
    assert second.branch != first.branch
    branches = git(repo, "branch", "--list")
    assert first.branch in branches
    assert second.branch in branches


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


def test_a_built_recommendation_stops_waiting_to_be_built(repo, writable, accepted):
    """The branch exists, so `accepted` is no longer the truth.

    Left unmoved, the status view reported an implemented recommendation as
    still awaiting implementation and its `implemented` stage was permanently
    empty.
    """
    from modules.improve.decide import IMPLEMENTED, get_recommendation

    run(writable, accepted)

    assert get_recommendation(writable.id, accepted)["status"] == IMPLEMENTED


def test_the_agent_that_built_it_is_recorded_as_having_moved_it(
    repo, writable, accepted
):
    from modules.improve.decide import history

    outcome = run(writable, accepted)

    moves = [h for h in history(accepted) if h["to_status"] == "implemented"]
    assert len(moves) == 1
    assert moves[0]["actor"] == outcome.pairing.implementer
    assert moves[0]["actor"] != "human"


def test_failing_tests_do_not_decide_the_outcome(
    repo, writable, accepted, monkeypatch
):
    """Built is not the same as worked, and only a human records the latter.

    A branch whose tests fail still reaches `implemented` -- the agent says
    what it did, the human says whether it was any good. The suite is faked
    rather than really run: what is under test is what happens downstream of
    a failure, and a real run would only prove `pytest` is on PATH.
    """
    from modules.improve.action import implement as module
    from modules.improve.decide import IMPLEMENTED, get_recommendation

    monkeypatch.setattr(
        module,
        "_run_suites",
        lambda *a, **k: TestResult("pytest -q", False, "1 failed"),
    )
    outcome = run(writable, accepted, run_tests_enabled=True)

    assert outcome.ok
    assert outcome.tests.passed is False
    row = get_recommendation(writable.id, accepted)
    assert row["status"] == IMPLEMENTED
    assert row["observed_value"] is None


def test_a_failed_run_leaves_it_accepted_so_it_can_be_retried(
    repo, writable, accepted
):
    from modules.improve.decide import ACCEPTED as STILL, get_recommendation

    (repo / "scratch.txt").write_text("notes\n")
    outcome = run(writable, accepted)

    assert not outcome.ok
    assert get_recommendation(writable.id, accepted)["status"] == STILL


def test_building_it_twice_is_refused_with_what_to_do_instead(
    repo, writable, accepted
):
    run(writable, accepted)
    second = run(writable, accepted)

    assert not second.ok
    assert "already been built" in second.error
    assert "--successful" in second.error


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


# -- picking up after a run that was killed --------------------------------


def _interrupted(repo, writable, accepted):
    """Leave exactly what a killed run leaves: its branch checked out, its
    work uncommitted, and a row still marked started."""
    from modules.improve.action.implement import branch_name
    from modules.improve.persistence import record_implementation

    branch = branch_name(accepted, "Add a farewell function")
    git(repo, "checkout", "-q", "-b", branch)
    (repo / "half_written.py").write_text("VALUE = 1\n")
    record_implementation(
        recommendation_id=accepted,
        repository_id=writable.id,
        implemented_by="codex",
        branch=branch,
        base_branch="main",
    )
    return branch


def test_an_interrupted_run_is_recognised_rather_than_blamed_on_you(
    repo, writable, accepted
):
    """"You have uncommitted changes" about something ALENA wrote is unhelpful,
    and leaves the recommendation permanently unimplementable."""
    branch = _interrupted(repo, writable, accepted)

    outcome = run(writable, accepted)

    assert not outcome.ok
    assert "was interrupted" in outcome.error
    assert branch in outcome.error
    assert "--recover" in outcome.error


def test_nothing_is_discarded_without_being_asked(repo, writable, accepted):
    _interrupted(repo, writable, accepted)

    run(writable, accepted)

    assert (repo / "half_written.py").exists()


def test_recover_discards_it_and_starts_again(repo, writable, accepted):
    _interrupted(repo, writable, accepted)

    outcome = run(writable, accepted, recover=True)

    assert outcome.ok
    assert not (repo / "half_written.py").exists()
    assert outcome.files_changed == ["new_module.py"]


def test_your_own_uncommitted_work_is_still_refused(repo, writable, accepted):
    """Recovery is only for what an interrupted run of this recommendation
    left; it is not a licence to clean the workspace."""
    (repo / "app.py").write_text("someone was working here\n")

    outcome = run(writable, accepted, recover=True)

    assert not outcome.ok
    assert "uncommitted changes" in outcome.error
    assert "app.py" in outcome.error


def test_a_stale_row_for_another_branch_is_not_treated_as_this_one(
    repo, writable, accepted
):
    from modules.improve.persistence import record_implementation

    record_implementation(
        recommendation_id=accepted,
        repository_id=writable.id,
        implemented_by="codex",
        branch="alena/99-something-else",
        base_branch="main",
    )
    (repo / "scratch.txt").write_text("yours\n")

    outcome = run(writable, accepted)

    assert "uncommitted changes" in outcome.error


# -- the two failures the first real implementation exposed -----------------


def test_pytest_is_found_in_the_project_virtualenv(tmp_path):
    """A bare `pytest` is on PATH only if a venv happens to be activated, and
    launchd activates nothing. The verification step reported "runner not
    found" while the implementing agent, which looked, ran the same suite."""
    from modules.improve.action.verify import detect_test_command

    runner = tmp_path / ".venv" / "bin" / "pytest"
    runner.parent.mkdir(parents=True)
    runner.write_text("#!/bin/sh\n")

    command = detect_test_command(tmp_path, ["conftest.py"], changed=["a.py"])

    assert str(runner) in command


def test_a_subproject_falls_back_to_the_repository_virtualenv(tmp_path):
    runner = tmp_path / ".venv" / "bin" / "pytest"
    runner.parent.mkdir(parents=True)
    runner.write_text("#!/bin/sh\n")
    (tmp_path / "backend").mkdir()

    command = detect_test_command(
        tmp_path, ["backend/conftest.py"], changed=["backend/a.py"]
    )

    assert str(runner) in command


def test_without_a_virtualenv_it_still_asks_for_pytest(tmp_path):
    """Reporting "not found" beats running ALENA's own interpreter against
    somebody else's dependencies."""
    from modules.improve.action.verify import detect_test_command

    assert detect_test_command(tmp_path, ["conftest.py"], changed=["a.py"]) == "pytest -q"


def test_an_unconfigured_reviewer_is_known_before_the_work(monkeypatch):
    from modules.improve.action.verify import reviewer_unavailable

    monkeypatch.delenv("CLAUDE_ROUTINE_URL", raising=False)
    assert "CLAUDE_ROUTINE_URL" in (reviewer_unavailable("claude") or "")

    monkeypatch.setenv("CLAUDE_ROUTINE_URL", "https://example.invalid/hook")
    assert reviewer_unavailable("claude") is None


def test_a_failed_review_does_not_read_as_a_verdict():
    """"claude says error" reads like a judgement. It is the absence of one."""
    from modules.improve.action.implement import ImplementationRun
    from modules.improve.action.verify import DiffReview

    run = ImplementationRun(repository_id="sample", recommendation_id=1)
    run.branch = "alena/1-x"
    run.review = DiffReview("claude", "error", "", "CLAUDE_ROUTINE_URL is not set")

    assert "NOT reviewed by claude" in run.describe()
