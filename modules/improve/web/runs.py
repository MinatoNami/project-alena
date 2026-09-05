"""Running pipeline steps in the background, on request.

A scan of four repositories takes about two minutes and a Codex review takes
the better part of a minute per observation, so none of these can be a
synchronous request. Each one starts a subprocess and the caller polls.

**A subprocess, not a thread.** It runs the same wrapper launchd runs, so a
button and a timer take identical paths -- including the PATH fixes and the
.env sourcing that only exist in that script. It also keeps the work off the
API's own interpreter, which matters because the store hands out one
connection per thread and a long job holding one is a connection nobody else
can reuse.

**One at a time.** Every command here reads and writes the same database and
the same workspaces, and two scans racing would interleave writes for no
benefit. A second request while one is running is refused rather than queued:
queueing would let a stray double-click spend a second Codex review.

Runs live in memory. A restart forgets them, which is the right trade for
something whose durable output is already in the database -- and the launchd
jobs run the same commands without appearing here at all, so this was never
a complete history of anything.
"""

from __future__ import annotations

import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = REPO_ROOT / "scripts" / "alena_improve.sh"

MAX_OUTPUT_LINES = 500
# A steer, not an essay. Long enough for a paragraph of direction, short
# enough that it cannot crowd out the prompt it is being added to.
MAX_FOCUS_CHARS = 2000
KEEP_RUNS = 20


@dataclass(frozen=True)
class Command:
    """A pipeline step the dashboard is allowed to start."""

    key: str
    label: str
    args: List[str]
    description: str
    # Whether it spends anything beyond local compute. Shown in the UI: a
    # button that quietly costs Codex quota is a button people regret.
    costs: Optional[str] = None
    # Named arguments the caller must supply, appended in this order. Only
    # `implement` has any -- it acts on one recommendation rather than on
    # everything.
    parameters: tuple = ()
    # Whether a free-text steer from the operator is passed to this command.
    # Unlike research text it is trusted -- it arrives from the person running
    # ALENA, through an interface only they can reach.
    accepts_focus: bool = False
    # Writes to a repository. The UI puts these behind a confirmation, and
    # nothing in this class is what actually authorises the write: the
    # registry capability, the accepted status and the gateway grant are.
    writes: bool = False

    def build(
        self, values: Dict[str, str], focus: Optional[str] = None
    ) -> List[str]:
        missing = [p for p in self.parameters if not values.get(p)]
        if missing:
            raise ValueError(f"{self.key} needs {', '.join(missing)}")

        args = [*self.args, *(str(values[p]) for p in self.parameters)]
        if focus and (focus or "").strip():
            if not self.accepts_focus:
                raise ValueError(f"{self.key} does not take a focus")
            # Passed as one argv element, never through a shell, so its
            # content cannot become further arguments.
            args += ["--focus", focus.strip()[:MAX_FOCUS_CHARS]]
        return args


COMMANDS: Dict[str, Command] = {
    c.key: c
    for c in [
        Command(
            "cycle",
            "Run a cycle",
            ["cycle", "--all"],
            "Scan, ingest whatever research has been dropped, review what is new, "
            "score it and refresh the portfolio. The same pass the nightly job "
            "runs. Stops at the approval gate: nothing is built.",
            costs="one Codex call per new observation",
            accepts_focus=True,
        ),
        Command(
            "scan",
            "Scan repositories",
            ["scan", "--all"],
            "Refresh git state, dependencies and TODOs. Unchanged repositories "
            "are skipped without reaching the model.",
            accepts_focus=True,
        ),
        Command(
            "review",
            "Review new observations",
            ["review", "--all"],
            "Put each new research observation to Codex.",
            costs="one Codex call per new observation",
            accepts_focus=True,
        ),
        Command(
            "recommend",
            "Score and write reports",
            ["recommend", "--all"],
            "Score everything reviewed and rewrite the recommendation reports.",
        ),
        Command(
            "escalate-dry-run",
            "Preview Claude escalation",
            ["review", "--all", "--agent", "claude", "--dry-run"],
            "Show which candidates would go to Claude, and why. Calls nothing.",
        ),
        Command(
            "portfolio",
            "Refresh portfolio",
            ["portfolio"],
            "Recompute shared technology and divergent pins across repositories.",
        ),
        Command(
            "implement",
            "Implement",
            ["implement"],
            "Create a branch, have Codex make the change, run the tests, and "
            "have the diff independently reviewed. Nothing is pushed and "
            "nothing is merged.",
            costs="a Codex session, and a branch in the repository",
            parameters=("repository_id", "recommendation_id"),
            writes=True,
        ),
    ]
}

# `ingest-research` is deliberately absent: it needs a file path, and a
# browser should not be choosing one.


@dataclass
class Run:
    id: str
    command: str
    label: str
    started_at: str
    detail: Optional[str] = None
    state: str = "running"  # running | finished | failed
    exit_code: Optional[int] = None
    finished_at: Optional[str] = None
    output: List[str] = field(default_factory=list)

    def to_dict(self, include_output: bool = True) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "command": self.command,
            "label": self.label,
            "detail": self.detail,
            "state": self.state,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if include_output:
            payload["output"] = self.output
        return payload


class Busy(RuntimeError):
    """Something is already running."""


class Runner:
    def __init__(self, wrapper: Optional[Path] = None):
        self._wrapper = wrapper or WRAPPER
        self._runs: List[Run] = []
        self._current: Optional[Run] = None
        self._lock = threading.Lock()

    @property
    def current(self) -> Optional[Run]:
        return self._current

    def runs(self) -> List[Run]:
        return list(reversed(self._runs))

    def get(self, run_id: str) -> Optional[Run]:
        return next((r for r in self._runs if r.id == run_id), None)

    def start(
        self,
        key: str,
        parameters: Optional[Dict[str, str]] = None,
        focus: Optional[str] = None,
    ) -> Run:
        command = COMMANDS.get(key)
        if command is None:
            raise KeyError(key)
        args = command.build(parameters or {}, focus)

        with self._lock:
            if self._current is not None and self._current.state == "running":
                raise Busy(
                    f"{self._current.label} is already running. These share a "
                    "database and the same workspaces, so they run one at a time."
                )
            run = Run(
                id=uuid.uuid4().hex[:12],
                command=key,
                label=command.label,
                detail=" ".join(args[1:]) if len(args) > 1 else None,
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._current = run
            self._runs.append(run)
            del self._runs[:-KEEP_RUNS]

        threading.Thread(
            target=self._execute, args=(run, args), daemon=True,
            name=f"alena-run:{key}",
        ).start()
        return run

    def _execute(self, run: Run, args: List[str]) -> None:
        try:
            process = subprocess.Popen(
                [str(self._wrapper), *args],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Unbuffered, or nothing appears until the run ends. Python
                # block-buffers stdout when it is a pipe, and a pipe is
                # exactly what this is -- so a six-minute implementation shows
                # a blank panel and then everything at once.
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                bufsize=1,
            )
        except OSError as exc:
            run.output.append(f"could not start: {exc}")
            run.state = "failed"
            run.exit_code = -1
            run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._release(run)
            return

        assert process.stdout is not None
        for line in process.stdout:
            run.output.append(line.rstrip())
            # Bounded: a scan of a large portfolio is chatty, and this is held
            # in memory for a page that only shows the tail anyway.
            del run.output[:-MAX_OUTPUT_LINES]

        run.exit_code = process.wait()
        run.state = "finished" if run.exit_code == 0 else "failed"
        run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._release(run)

    def _release(self, run: Run) -> None:
        with self._lock:
            if self._current is run:
                self._current = None


_runner: Optional[Runner] = None


def get_runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner()
    return _runner


def reset_runner() -> None:
    global _runner
    _runner = None
