"""Run a repository's tests, and get the diff independently reviewed."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from modules.core.controller.logger import logger

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT = 900


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # a dataclass, not something for pytest to collect


    command: Optional[str]
    passed: Optional[bool]
    output: str = ""
    directory: str = ""

    @property
    def ran(self) -> bool:
        return self.passed is not None

    def describe(self) -> str:
        if not self.ran:
            # Why they did not run matters. "not run" reads like "there were
            # none"; "the runner is missing" is a thing someone can fix.
            detail = (self.output or "no test command detected").strip()
            return f"tests not run ({detail})"
        where = f" in {self.directory}" if self.directory else ""
        return f"tests {'passed' if self.passed else 'FAILED'} ({self.command}{where})"


def _pytest_command(workspace: Path, directory: str) -> str:
    """`pytest`, from the project's own virtualenv when it has one.

    A bare `pytest` is only on PATH if the venv happens to be activated, and
    launchd activates nothing. This repository's own runner lives in
    `.venv/bin/pytest`, so the action agent's verification step reported "test
    runner not found" while the implementing agent, which looked, ran the same
    suite successfully.

    Deliberately not `sys.executable -m pytest`: that is *ALENA's* interpreter,
    and running it against another repository's tests would use ALENA's
    installed packages rather than the ones under test. Better to report that
    no runner was found than to run the wrong one.
    """
    root = workspace / directory if directory else workspace
    for candidate in (".venv/bin/pytest", "venv/bin/pytest", ".venv/Scripts/pytest.exe"):
        runner = root / candidate
        if runner.exists():
            return f"{shlex.quote(str(runner))} -q"
        # A monorepo subproject often shares the repository root's virtualenv.
        shared = workspace / candidate
        if directory and shared.exists():
            return f"{shlex.quote(str(shared))} -q"
    return "pytest -q"


def _command_for(workspace: Path, directory: str, names: set) -> Optional[str]:
    """How the project rooted at `directory` runs its tests, if it says."""
    if {"pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg"} & names:
        return _pytest_command(workspace, directory)
    if "package.json" in names:
        try:
            manifest = json.loads(
                (workspace / directory / "package.json").read_text()
                if directory
                else (workspace / "package.json").read_text()
            )
        except (OSError, json.JSONDecodeError):
            return None
        if "test" in (manifest.get("scripts") or {}):
            return "npm test --silent"
        return None
    if "go.mod" in names:
        return "go test ./..."
    return None


def detect_test_suites(
    workspace: Path, tracked: List[str], changed: Optional[List[str]] = None
) -> List[Tuple[str, str]]:
    """Every (command, directory) the change implicates, nearest manifest first.

    A monorepo keeps its manifests in subdirectories -- LumaIndex has
    `frontend/package.json` and `backend/pytest.ini`, and nothing at the root.
    Looking only at the root found neither, so a change to the frontend went
    to review with its tests never run, which is the worst available answer:
    it reads as "there were no tests" rather than "nobody looked".

    Driven by what changed, so a one-line frontend edit does not run the
    backend suite. With no change list, every project found is returned.
    """
    manifests: Dict[str, set] = {}
    for relative in tracked:
        path = Path(relative)
        if path.name in {
            "pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg",
            "package.json", "go.mod",
        }:
            directory = str(path.parent) if str(path.parent) != "." else ""
            manifests.setdefault(directory, set()).add(path.name)

    if changed:
        # Keep the projects that own a changed file: walk up from each change
        # and take the nearest directory that has a manifest.
        wanted = set()
        for relative in changed:
            parts = Path(relative).parent
            candidates = [str(parts), *(str(p) for p in parts.parents)]
            for candidate in candidates:
                key = "" if candidate == "." else candidate
                if key in manifests:
                    wanted.add(key)
                    break
        manifests = {k: v for k, v in manifests.items() if k in wanted}

    suites = []
    for directory in sorted(manifests, key=lambda d: (d.count("/"), d)):
        command = _command_for(workspace, directory, manifests[directory])
        if command:
            suites.append((command, directory))
    return suites


def detect_test_command(
    workspace: Path, tracked: List[str], changed: Optional[List[str]] = None
) -> Optional[str]:
    """The first test command the change implicates, or None.

    A guess, and treated as one: an unrecognised project reports "not run"
    rather than having something invented for it. Claiming tests passed when
    none ran is the worst possible answer here.
    """
    suites = detect_test_suites(workspace, tracked, changed)
    return suites[0][0] if suites else None


def run_tests(
    workspace: Path,
    command: Optional[str],
    timeout: int = DEFAULT_TIMEOUT,
    directory: str = "",
) -> TestResult:
    if not command:
        return TestResult(command=None, passed=None, output="no test command detected")

    try:
        process = subprocess.run(
            shlex.split(command),
            cwd=str(workspace / directory) if directory else str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return TestResult(command, None, f"test runner not found: {exc}")
    except subprocess.TimeoutExpired:
        return TestResult(command, False, f"tests timed out after {timeout}s")

    output = (process.stdout + process.stderr)[-MAX_OUTPUT_CHARS:]
    return TestResult(command=command, passed=process.returncode == 0, output=output)


@dataclass(frozen=True)
class DiffReview:
    agent: str
    verdict: str
    body: str
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def approves(self) -> bool:
        return self.verdict == "supported"


REVIEW_PROMPT = """You are reviewing an implementation produced by a different
agent. It has not been merged and will not be without a human deciding to.

Do not modify anything. Judge the change as written.

Recommendation being implemented:
{title}

{body}

Test result: {tests}

Diff:
```diff
{diff}
```

Say whether this change is correct, complete and safe to open as a draft pull
request. Cover: whether it does what the recommendation asked, anything it
breaks, anything missing, and anything unsafe.

End with a fenced JSON block and nothing after it:

```json
{{"verdict": "supported | rejected | unclear", "summary": "one sentence"}}
```"""


def reviewer_unavailable(agent: str) -> Optional[str]:
    """Why `agent` cannot review right now, or None if it can.

    Checked before the implementation starts. Finding out afterwards means an
    unattended run has already spent an implementation to discover that the
    second half of "one model writes, the other checks" was never going to
    happen -- and the discovery arrives as a warning in a log nobody reads.
    """
    if agent != "claude":
        return None
    from ..agents.claude_review import RoutineConfig, RoutineNotConfigured

    try:
        RoutineConfig.from_env()
    except RoutineNotConfigured as exc:
        return str(exc)
    return None


def review_diff(
    agent: str,
    title: str,
    body: str,
    diff: str,
    tests: TestResult,
    *,
    caller=None,
) -> DiffReview:
    """Have `agent` judge a diff it did not write."""
    from ..agents.claude_review import call_routine
    from ..agents.codex_review import parse_verdict

    caller = caller or call_routine
    prompt = REVIEW_PROMPT.format(
        title=title,
        body=(body or "").strip()[:4000],
        tests=tests.describe(),
        diff=diff[:30000],
    )

    try:
        text = caller(prompt, config=None, metadata={"kind": "implementation-review"})
    except Exception as exc:  # noqa: BLE001 - an unreviewed diff is still a diff
        logger.warning(f"Implementation review by {agent} failed: {exc!r}")
        return DiffReview(agent, "error", "", f"{type(exc).__name__}: {exc}")

    payload = parse_verdict(text)
    return DiffReview(agent=agent, verdict=payload["verdict"], body=text)
