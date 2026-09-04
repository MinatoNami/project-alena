"""Render recommendations as markdown.

The spec's format, including its `[ ] Accept / [ ] Reject` block. That block
is a *view*, not an input: ticking a box changes nothing, because parsing a
human-edited markdown file back into state is fragile in a way that loses
decisions. The command that actually records one is printed next to it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..artifacts import intelligence_dir
from ..clock import label as timezone_label, now


def render_recommendation(row: Dict[str, Any], repository_id: str) -> str:
    confidence = row.get("confidence")
    confidence_text = f"{float(confidence) * 100:.0f}%" if confidence is not None else "unknown"
    score = row.get("score")
    score_text = f"{float(score):.2f}" if score is not None else "unscored"
    breakdown = row.get("score_breakdown_parsed") or {}

    return "\n".join(
        [
            f"## {row['title']}",
            "",
            f"Priority: {breakdown.get('priority', 'UNKNOWN')}",
            f"Score: {score_text}",
            f"Confidence: {confidence_text}",
            f"Estimated Effort: {row.get('estimated_effort') or 'unknown'}",
            "",
            (row.get("body") or "").strip(),
            "",
            "### Decision",
            "",
            "[ ] Accept",
            "[ ] Reject",
            "[ ] Revisit",
            "",
            "_Ticking a box here does nothing. Record the decision with:_",
            "",
            "```bash",
            f"alena-improve decide {repository_id} {row['id']} --accept",
            f"alena-improve decide {repository_id} {row['id']} --reject --reason \"...\"",
            "```",
            "",
        ]
    )


def render_report(
    repository_name: str,
    repository_id: str,
    rows: List[Dict[str, Any]],
    skipped: Optional[List[Dict[str, Any]]] = None,
    rejected: Optional[List[Dict[str, Any]]] = None,
) -> str:
    lines = [
        f"# {repository_name} — recommendations",
        "",
        f"_Generated {now()} ({timezone_label()}). {len(rows)} open recommendation(s)._",
        "",
    ]

    if not rows:
        lines += ["_Nothing to recommend from the research ingested so far._", ""]
    else:
        lines += ["| Priority | Score | Effort | Title |", "|---|---|---|---|"]
        for row in rows:
            breakdown = row.get("score_breakdown_parsed") or {}
            score = row.get("score")
            score_cell = f"{float(score):.2f}" if score is not None else "?"
            lines.append(
                f"| {breakdown.get('priority', '?')} | {score_cell} "
                f"| {row.get('estimated_effort') or '?'} | {row['title']} |"
            )
        lines += [""]
        for row in rows:
            lines.append(render_recommendation(row, repository_id))
            lines.append("---")
            lines.append("")

    if rejected:
        lines += [
            "## Rejected by engineering review",
            "",
            "The reviewer judged these unsound for this repository. They are "
            "recorded so the same idea is recognised if it arrives again.",
            "",
        ]
        for row in rejected:
            lines.append(f"- **{row['title']}** — {row.get('reason') or 'rejected'}")
        lines += [""]

    if skipped:
        lines += [
            "## Skipped as duplicates",
            "",
            "These observations were not reviewed, because they restate "
            "something already proposed.",
            "",
        ]
        for row in skipped:
            lines.append(f"- **{row['title']}** — {row.get('duplicate_reason') or 'duplicate'}")
        lines += [""]

    return "\n".join(lines).rstrip() + "\n"


def write_report(
    repository_id: str,
    text: str,
    root: Optional[Path] = None,
    on: Optional[str] = None,
) -> List[Path]:
    """Write the dated report and refresh `latest.md`."""
    base = (root or intelligence_dir()) / "recommendations" / repository_id
    base.mkdir(parents=True, exist_ok=True)

    dated = base / f"{on or date.today().isoformat()}.md"
    latest = base / "latest.md"
    dated.write_text(text)
    latest.write_text(text)
    return [dated, latest]


def render_portfolio(snapshot: Dict[str, Any]) -> str:
    """The portfolio view, as a human reads it."""
    repositories = snapshot.get("repositories") or {}
    shared = snapshot.get("shared") or {}
    divergence = snapshot.get("divergence") or []
    findings = snapshot.get("findings") or []

    lines = [
        "# Portfolio",
        "",
        f"_Generated {now()} ({timezone_label()}) across {len(repositories)} repositories._",
        "",
        "| Repository | Technologies |",
        "|---|---|",
    ]
    for repository_id, info in repositories.items():
        lines.append(f"| {info.get('name', repository_id)} | {len(info.get('technologies') or [])} |")
    lines.append("")

    if divergence:
        lines += [
            "## Dependencies pinned differently",
            "",
            "Nobody decided these; they accumulated. The repositories that drift",
            "furthest apart are where a shared fix stops applying cleanly.",
            "",
            "| Dependency | Pins |",
            "|---|---|",
        ]
        for item in divergence:
            pins = "; ".join(
                f"{repo} `{spec or 'unpinned'}`"
                for repo, spec in (item.get("specifiers") or {}).items()
            )
            lines.append(f"| {item['name']} ({item['ecosystem']}) | {pins} |")
        lines.append("")

    dependencies = {
        key.split(":", 1)[1]: users
        for key, users in shared.items()
        if key.startswith("dependency:")
    }
    if dependencies:
        lines += ["## Shared dependencies", "", "| Dependency | Used by |", "|---|---|"]
        for name, users in sorted(dependencies.items()):
            lines.append(f"| {name} | {', '.join(users)} |")
        lines.append("")

    travelling = [f for f in findings if f["kind"] == "travelling-recommendation"]
    if travelling:
        lines += [
            "## Work that might travel",
            "",
            "Accepted for one repository, in a technology another one also uses.",
            "Nothing is proposed automatically -- a cross-repository finding is an",
            "observation, and turning one into a recommendation would let it skip",
            "the review every other recommendation goes through.",
            "",
        ]
        for finding in travelling:
            lines.append(f"- **{finding['title']}** — {finding['detail']}")
            lines.append(f"  - relevant to: {', '.join(finding['repositories'])}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_portfolio(text: str, root: Optional[Path] = None) -> List[Path]:
    base = (root or intelligence_dir()) / "portfolio"
    base.mkdir(parents=True, exist_ok=True)
    dated = base / f"{date.today().isoformat()}.md"
    latest = base / "latest.md"
    dated.write_text(text)
    latest.write_text(text)
    return [dated, latest]
