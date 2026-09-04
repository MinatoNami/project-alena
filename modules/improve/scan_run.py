"""One repository scan.

This is Trigger B from the spec -- the nightly local pass. It runs against
every declared repository whether or not anything happened, so the expensive
part is gated on the fingerprint: an unchanged repository costs a handful of
git commands and never reaches the model.

Nothing here calls a cloud agent, and nothing here writes to a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.core.controller.logger import logger

from .artifacts import utcnow, write_profile
from .intelligence import summarize_changes, summarize_repository
from .persistence import latest_scan, record_scan, upsert_repository
from .registry import Repository
from .scan import (
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

README_NAMES = ("README.md", "README.rst", "README.txt", "README")


@dataclass
class ScanOutcome:
    repository_id: str
    ok: bool
    changed: bool = False
    skipped: bool = False
    scan: Dict[str, Any] = field(default_factory=dict)
    profile_path: Optional[Path] = None
    error: Optional[str] = None

    def describe(self) -> str:
        if not self.ok:
            return f"{self.repository_id}: failed — {self.error}"
        if self.skipped:
            return f"{self.repository_id}: unchanged, skipped"
        head = (self.scan.get("head_sha") or "")[:8]
        return (
            f"{self.repository_id}: scanned "
            f"({self.scan.get('file_count', 0)} files, {head or 'no HEAD'})"
        )


def _read_readme(workspace: Path, tracked: List[str]) -> Optional[str]:
    tracked_set = set(tracked)
    for name in README_NAMES:
        if name in tracked_set:
            try:
                return (workspace / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return None


def scan_repository(
    repository: Repository,
    *,
    force: bool = False,
    summarize: bool = True,
    note: Optional[str] = None,
    intelligence_root: Optional[Path] = None,
    conn=None,
) -> ScanOutcome:
    """Scan one repository and persist what was found."""
    repository.require("analyze")
    git = GitRepository(repository.workspace)

    if not git.exists():
        return ScanOutcome(
            repository.id,
            ok=False,
            error=f"workspace does not exist: {repository.workspace}",
        )

    try:
        state = git.state()
    except GitError as exc:
        return ScanOutcome(repository.id, ok=False, error=str(exc))

    upsert_repository(repository, conn)

    current = fingerprint(state)
    previous = latest_scan(repository.id, conn)
    changed = has_changed(current, previous["fingerprint"] if previous else None)

    if not changed and not force:
        logger.info(f"{repository.id}: unchanged ({current[:12]}), skipping")
        return ScanOutcome(
            repository.id, ok=True, changed=False, skipped=True, scan=previous or {}
        )

    languages = detect_languages(state.tracked_files)
    dependencies = [d.to_dict() for d in extract_dependencies(
        repository.workspace, state.tracked_files
    )]
    found_todos = parse_grep(git.grep(MARKERS))
    todos = [t.to_dict() for t in found_todos]
    todo_delta = diff_todos(found_todos, (previous or {}).get("todos") or [])

    scan: Dict[str, Any] = {
        "repository_id": repository.id,
        "name": repository.name,
        "workspace": str(repository.workspace),
        "scanned_at": utcnow(),
        "fingerprint": current,
        "head_sha": state.head_sha,
        "branch": state.branch,
        "dirty": state.dirty,
        "changed": changed,
        "file_count": len(state.tracked_files),
        "languages": languages,
        "dependencies": dependencies,
        "todos": todos,
        "todo_delta": todo_delta,
        "recent_commits": [c.to_dict() for c in state.recent_commits],
    }

    if summarize:
        # Both summaries are best-effort: an unattended nightly run must not
        # fail because LM Studio was asleep.
        scan["summary"] = summarize_repository(
            name=repository.name,
            languages=languages,
            dependencies=dependencies,
            file_count=len(state.tracked_files),
            readme=_read_readme(repository.workspace, state.tracked_files),
            recent_subjects=[c.subject for c in state.recent_commits],
            note=note,
        )
        previous_head = (previous or {}).get("head_sha")
        if previous_head and state.head_sha and previous_head != state.head_sha:
            scan["diff_summary"] = summarize_changes(
                name=repository.name,
                diff_stat=git.diff_stat(previous_head),
                commit_subjects=[
                    c.subject
                    for c in state.recent_commits
                    if c.sha != previous_head
                ],
                diff=git.diff(previous_head),
            )

    record_scan(scan, conn)
    profile_path = write_profile(scan, intelligence_root)

    return ScanOutcome(
        repository.id,
        ok=True,
        changed=changed,
        scan=scan,
        profile_path=profile_path,
    )
