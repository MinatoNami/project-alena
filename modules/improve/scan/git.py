"""Read-only git inspection of a registry workspace.

Everything here shells out to `git -C <workspace>`. Two rules hold throughout:
the workspace comes from the registry and never from model output, and no
command is ever run through a shell, so a path or branch name cannot become
an argument list.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

DEFAULT_TIMEOUT = 30


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    date: str
    subject: str

    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "author": self.author,
            "date": self.date,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class GitState:
    head_sha: Optional[str]
    branch: Optional[str]
    dirty_files: List[str] = field(default_factory=list)
    tracked_files: List[str] = field(default_factory=list)
    recent_commits: List[Commit] = field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return bool(self.dirty_files)


class GitRepository:
    def __init__(self, workspace: Path, timeout: int = DEFAULT_TIMEOUT):
        self.workspace = Path(workspace)
        self.timeout = timeout

    # -- plumbing ----------------------------------------------------------

    def run(self, *args: str, check: bool = True) -> str:
        try:
            process = subprocess.run(
                # quotePath=false or git escapes any non-ASCII path -- a file
                # called "Athena — PRD.md" comes back as an octal-escaped,
                # double-quoted string that no later path join can open.
                ["git", "-C", str(self.workspace), "-c", "core.quotePath=false", *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitError("git is not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(
                f"git {' '.join(args)} timed out after {self.timeout}s"
            ) from exc

        if process.returncode != 0:
            if not check:
                return ""
            raise GitError(
                f"git {' '.join(args)} failed in {self.workspace}: "
                f"{process.stderr.strip() or process.returncode}"
            )
        return process.stdout

    def _lines(self, *args: str, check: bool = True) -> List[str]:
        return [line for line in self.run(*args, check=check).splitlines() if line]

    # -- queries -----------------------------------------------------------

    def exists(self) -> bool:
        return self.workspace.is_dir()

    def is_repository(self) -> bool:
        if not self.exists():
            return False
        return self.run("rev-parse", "--is-inside-work-tree", check=False).strip() == "true"

    def head_sha(self) -> Optional[str]:
        # An empty repository has no HEAD, which is a valid state, not an error.
        return self.run("rev-parse", "HEAD", check=False).strip() or None

    def branch(self) -> Optional[str]:
        name = self.run("rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
        return name or None

    def branches(self) -> List[str]:
        return self._lines("for-each-ref", "--format=%(refname:short)", "refs/heads")

    def dirty_files(self) -> List[str]:
        return [line[3:] for line in self._lines("status", "--porcelain")]

    def tracked_files(self) -> List[str]:
        return self._lines("ls-files")

    def recent_commits(self, limit: int = 20) -> List[Commit]:
        # %x1f is the unit separator: subjects contain everything else.
        raw = self._lines(
            "log", f"-n{limit}", "--no-merges", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s",
            check=False,
        )
        commits = []
        for line in raw:
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(Commit(*parts))
        return commits

    def changed_files(self, since: str, until: str = "HEAD") -> List[str]:
        """Paths changed between two revisions, ignoring an unknown `since`."""
        raw = self.run("diff", "--name-only", f"{since}..{until}", check=False)
        return [line for line in raw.splitlines() if line]

    def diff_stat(self, since: str, until: str = "HEAD") -> str:
        return self.run("diff", "--stat", f"{since}..{until}", check=False).strip()

    def diff(self, since: str, until: str = "HEAD", max_chars: int = 20000) -> str:
        """A truncated diff, sized for a model context rather than a human."""
        raw = self.run("diff", f"{since}..{until}", check=False)
        if len(raw) <= max_chars:
            return raw
        return raw[:max_chars] + f"\n... [truncated at {max_chars} characters]"

    def grep(self, patterns: Sequence[str], max_results: int = 500) -> List[str]:
        """`git grep` over tracked files only.

        Tracked-only is the point: it skips node_modules, .venv and build
        output without needing to know what any of those are called.

        The pattern is deliberately looser than what parse_grep accepts -- no
        word boundaries here. git's regex flavour is not guaranteed to support
        `\b`, and a pattern that silently matches nothing would drop every
        TODO in the repository without saying so. Over-matching costs a few
        discarded lines; under-matching loses the signal.
        """
        args = ["grep", "-n", "-I", "--no-color", "-E"]
        args.append("|".join(patterns))
        return self._lines(*args, check=False)[:max_results]

    def state(self, commit_limit: int = 20) -> GitState:
        if not self.is_repository():
            raise GitError(f"{self.workspace} is not a git repository")
        return GitState(
            head_sha=self.head_sha(),
            branch=self.branch(),
            dirty_files=self.dirty_files(),
            tracked_files=self.tracked_files(),
            recent_commits=self.recent_commits(commit_limit),
        )
