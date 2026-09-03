"""Run a repository's tests, and get the diff independently reviewed."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from modules.core.controller.logger import logger

MAX_OUTPUT_CHARS = 20000
DEFAULT_TIMEOUT = 900


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # a dataclass, not something for pytest to collect


    command: Optional[str]
    passed: Optional[bool]
    output: str = ""

    @property
    def ran(self) -> bool:
        return self.passed is not None

    def describe(self) -> str:
        if not self.ran:
            # Why they did not run matters. "not run" reads like "there were
            # none"; "the runner is missing" is a thing someone can fix.
            detail = (self.output or "no test command detected").strip()
            return f"tests not run ({detail})"
        return f"tests {'passed' if self.passed else 'FAILED'} ({self.command})"


def detect_test_command(workspace: Path, tracked: List[str]) -> Optional[str]:
    """Guess how this repository runs its tests.

    A guess, and treated as one: an unrecognised project reports "not run"
    rather than having something invented for it. Claiming tests passed when
    none ran is the worst possible answer here.
    """
    names = {Path(p).name for p in tracked}
    if {"pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg"} & names:
        return "pytest -q"
    if any(p.startswith("tests/") or "/tests/" in p for p in tracked):
        if any(p.endswith(".py") for p in tracked):
            return "pytest -q"
    if "package.json" in names:
        try:
            manifest = json.loads((workspace / "package.json").read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if "test" in (manifest.get("scripts") or {}):
            return "npm test --silent"
    if "go.mod" in names:
        return "go test ./..."
    return None


def run_tests(
    workspace: Path,
    command: Optional[str],
    timeout: int = DEFAULT_TIMEOUT,
) -> TestResult:
    if not command:
        return TestResult(command=None, passed=None, output="no test command detected")

    try:
        process = subprocess.run(
            shlex.split(command),
            cwd=str(workspace),
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
