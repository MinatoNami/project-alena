"""The context package every agent receives.

Written once per repository and reused by every agent that looks at it, so
Codex, Claude and the local model all reason from the same picture and none of
them has to re-derive it by scanning the repository again.

The rejected-recommendations file is the one that earns its place. Dedup
catches a reworded proposal only when an embedding model is loaded; when it is
not, a rewording reaches review anyway. Handing the reviewer the list of things
already turned down, with the reason each was turned down, is what catches it
then -- so this file is not documentation, it is the second half of dedup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .artifacts import repository_dir
from .clock import now
from .registry import Repository

CONTEXT_DIRNAME = ".context"


def context_dir(repository_id: str, root: Optional[Path] = None) -> Path:
    path = repository_dir(repository_id, root) / CONTEXT_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _recommendation_lines(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "_none_\n"
    lines = []
    for row in rows:
        lines.append(f"## {row['title']}")
        lines.append("")
        if row.get("reason"):
            lines.append(f"**Reason:** {row['reason']}")
            lines.append("")
        if row.get("body"):
            lines.append(row["body"].strip())
            lines.append("")
    return "\n".join(lines)


def write_context_package(
    repository: Repository,
    scan: Optional[Dict[str, Any]],
    recommendations: Dict[str, List[Dict[str, Any]]],
    root: Optional[Path] = None,
) -> Path:
    """Write `.context/` and return its directory."""
    directory = context_dir(repository.id, root)
    scan = scan or {}

    (directory / "repository.yaml").write_text(
        yaml.safe_dump(
            {
                **repository.to_dict(),
                "generated_at": now(),
                "branch": scan.get("branch"),
                "head_sha": scan.get("head_sha"),
                "file_count": scan.get("file_count"),
            },
            sort_keys=False,
        )
    )

    architecture = [f"# {repository.name} — architecture", ""]
    if scan.get("summary"):
        architecture += [scan["summary"], ""]
    else:
        architecture += ["_No summary available; the local model was not reachable._", ""]
    languages = scan.get("languages") or {}
    if languages:
        architecture += ["## Languages", ""]
        architecture += [f"- {name}: {count} files" for name, count in languages.items()]
        architecture += [""]
    (directory / "architecture.md").write_text("\n".join(architecture))

    (directory / "dependencies.json").write_text(
        json.dumps(scan.get("dependencies") or [], indent=2)
    )

    changes = [f"# {repository.name} — recent changes", ""]
    if scan.get("diff_summary"):
        changes += [scan["diff_summary"], ""]
    commits = scan.get("recent_commits") or []
    if commits:
        changes += ["## Commits", ""]
        changes += [f"- `{c['sha'][:8]}` {c['subject']}" for c in commits[:30]]
        changes += [""]
    todos = scan.get("todos") or []
    if todos:
        changes += ["## Open TODO / FIXME", ""]
        changes += [
            f"- `{t['path']}:{t['line']}` {t['marker']} {t['text']}".rstrip()
            for t in todos[:40]
        ]
        changes += [""]
    (directory / "recent_changes.md").write_text("\n".join(changes))

    for name, key in (
        ("previous_recommendations.md", "all"),
        ("accepted_recommendations.md", "accepted"),
        ("rejected_recommendations.md", "rejected"),
    ):
        rows = recommendations.get(key) or []
        heading = f"# {repository.name} — {key} recommendations\n\n"
        if key == "rejected":
            heading += (
                "Do not propose these again. If a new observation is a "
                "restatement of one of them, say so rather than proposing it.\n\n"
            )
        (directory / name).write_text(heading + _recommendation_lines(rows))

    questions = [
        f"# {repository.name} — research questions",
        "",
        "What external developments in the last 30 days could materially improve",
        f"{repository.name}?",
        "",
        f"Domain tags: {', '.join(repository.tags) or 'none declared'}",
        "",
        "Produce evidence-backed observations. Do not recommend implementation.",
        "",
    ]
    (directory / "research_questions.md").write_text("\n".join(questions))

    return directory


def build_context_package(
    repository: Repository, root: Optional[Path] = None, conn=None
) -> Path:
    """Assemble the package from whatever has been scanned and decided so far."""
    from .persistence import latest_scan, recommendations_by_status

    return write_context_package(
        repository,
        latest_scan(repository.id, conn),
        recommendations_by_status(repository.id, conn),
        root,
    )
