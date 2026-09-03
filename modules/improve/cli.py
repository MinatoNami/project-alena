"""`alena-improve` -- the orchestrator's command line.

Every trigger in the spec is a subcommand here rather than a scheduler inside
the application. launchd survives reboots, a subcommand can be re-run by hand
when something looks wrong, and the same entry point is what a unit test calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .artifacts import ensure_layout, intelligence_dir
from .action.implement import implement
from .context_package import build_context_package
from .decide import (
    ABANDONED,
    ACCEPTED,
    RECOMMENDED,
    REJECTED,
    SUCCESSFUL,
    UNSUCCESSFUL,
    DecisionError,
    decide,
    history,
)
from .persistence import implementations_for, latest_scan, recommendations_for
from .query import portfolio_snapshot, search_capability
from .recommend.render import render_portfolio, write_portfolio
from .registry import RegistryError, Repository, load_registry
from .research import ingest_file, research_files
from .review_run import escalate_repository, recommend_repository, review_repository
from .scan_run import ScanOutcome, scan_repository
from .wiring import install_gateway


def _targets(registry, requested: Optional[str], every: bool) -> List[Repository]:
    if every:
        return registry.all()
    if not requested:
        raise RegistryError("Name a repository, or pass --all")
    return [registry.resolve(requested, "analyze")]


def cmd_scan(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    install_gateway(registry, args.policy)
    ensure_layout()

    try:
        targets = _targets(registry, args.repository, args.all)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not targets:
        print("No enabled repositories in the registry.")
        return 0

    outcomes: List[ScanOutcome] = []
    for repository in targets:
        try:
            outcome = scan_repository(
                repository, force=args.force, summarize=not args.no_llm
            )
        except RegistryError as exc:
            outcome = ScanOutcome(repository.id, ok=False, error=str(exc))
        outcomes.append(outcome)
        print(outcome.describe())
        if outcome.profile_path:
            print(f"  profile: {outcome.profile_path}")

    failed = [o for o in outcomes if not o.ok]
    if failed:
        print(f"\n{len(failed)} of {len(outcomes)} repositories failed.", file=sys.stderr)
        return 1
    return 0


def cmd_repos(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    repositories = registry.all(include_disabled=True)
    if not repositories:
        print("No repositories declared.")
        return 0

    if args.json:
        print(json.dumps([r.to_dict() for r in repositories], indent=2))
        return 0

    width = max(len(r.id) for r in repositories)
    for repository in repositories:
        writable = [
            name
            for name in ("modify", "create_branch", "create_pr", "merge")
            if repository.capabilities.allows(name)
        ]
        flags = ", ".join(writable) or "read-only"
        state = "" if repository.enabled else "  [disabled]"
        print(f"{repository.id:<{width}}  {flags:<40}  {repository.workspace}{state}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    repository = registry.resolve(args.repository)
    scan = latest_scan(repository.id)
    if scan is None:
        print(f"{repository.id} has not been scanned yet. Run: alena-improve scan {repository.id}")
        return 1
    if args.json:
        print(json.dumps(scan, indent=2, default=str))
        return 0

    print(f"{repository.name} ({repository.id})")
    print(f"  scanned    {scan['scanned_at']}")
    print(f"  branch     {scan['branch']} @ {(scan['head_sha'] or '')[:12]}")
    print(f"  files      {scan['file_count']}")
    print(f"  languages  {', '.join(scan['languages']) or 'unknown'}")
    print(f"  deps       {len(scan['dependencies'])}")
    print(f"  todos      {len(scan['todos'])}")
    if scan.get("summary"):
        print(f"\n{scan['summary']}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from modules.gateway.audit import AuditLog

    rows = AuditLog().recent(args.limit)
    if not rows:
        print("No tool invocations recorded yet.")
        return 0
    for row in rows:
        detail = row["denial_reason"] or row["error"] or ""
        print(
            f"{row['created_at']}  {row['outcome']:<8} {row['tool']:<24} "
            f"{row['agent']:<18} {detail}".rstrip()
        )
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    from modules.gateway.policy import resolve_policy_path
    from modules.store import resolve_db_path

    from .registry import resolve_registry_path

    print(f"registry      {resolve_registry_path(args.registry)}")
    print(f"tool policy   {resolve_policy_path(args.policy)}")
    print(f"database      {resolve_db_path()}")
    print(f"intelligence  {intelligence_dir()}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    ensure_layout()
    for repository in _targets(registry, args.repository, args.all):
        directory = build_context_package(repository)
        print(f"{repository.id}: {directory}")
    return 0


def cmd_ingest_research(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    ensure_layout()
    repository = registry.resolve(args.repository, "research")

    if args.from_dir:
        paths = research_files(Path(args.from_dir))
        if not paths:
            print(f"No markdown in {args.from_dir}")
            return 0
    else:
        paths = [Path(args.path)]

    failed = 0
    for path in paths:
        result = ingest_file(repository, path, source=args.source)
        print(f"{path.name}: {result.describe()}")
        for title in result.duplicates:
            print(f"  skipped: {title}")
        if not result.ok:
            failed += 1
    return 1 if failed else 0


def cmd_review(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    install_gateway(registry, args.policy)
    ensure_layout()

    failed = 0
    for repository in _targets(registry, args.repository, args.all):
        if args.agent == "claude":
            run = escalate_repository(
                repository,
                limit=args.limit,
                dry_run=args.dry_run,
                retry_failed=args.retry_failed,
            )
            print(run.describe())
            if args.dry_run:
                for line in run.reviewed:
                    print(f"  would escalate: {line}")
        else:
            run = review_repository(repository, limit=args.limit)
            print(run.describe())
        failed += len(run.failed)
    return 1 if failed else 0


def cmd_recommend(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    ensure_layout()

    for repository in _targets(registry, args.repository, args.all):
        run = recommend_repository(repository)
        print(run.describe())
        for path in run.written:
            print(f"  {path}")
    return 0


_STATUS_FLAGS = {
    "accept": ACCEPTED,
    "reject": REJECTED,
    "revisit": RECOMMENDED,
    "abandon": ABANDONED,
    "successful": SUCCESSFUL,
    "unsuccessful": UNSUCCESSFUL,
}


def cmd_decide(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    repository = registry.resolve(args.repository)

    chosen = [name for name in _STATUS_FLAGS if getattr(args, name, False)]
    if len(chosen) != 1:
        print(
            "error: choose exactly one of "
            f"--{', --'.join(_STATUS_FLAGS)}",
            file=sys.stderr,
        )
        return 2

    try:
        decision = decide(
            repository.id,
            args.id,
            _STATUS_FLAGS[chosen[0]],
            reason=args.reason,
            actor=args.actor,
            actual_effort=args.actual_effort,
            observed_value=args.observed_value,
            feedback=args.feedback,
        )
    except DecisionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(decision.describe())
    if decision.to_status == ACCEPTED:
        print(
            f"  implement with: alena-improve implement {repository.id} {args.id}"
        )
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    found = 0
    for repository in _targets(registry, args.repository, args.all or not args.repository):
        rows = recommendations_for(repository.id, args.status)
        if not rows:
            continue
        print(f"{repository.name} ({repository.id})")
        for row in rows:
            score = f"{row['score']:.2f}" if row["score"] is not None else "?"
            print(
                f"  #{row['id']:<4} {score:>5}  {row['status']:<12} {row['title']}"
            )
            found += 1
        print()
    if not found:
        print(f"Nothing with status {args.status!r}.")
    return 0


def cmd_implement(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    install_gateway(registry, args.policy)
    ensure_layout()

    try:
        repository = registry.resolve(args.repository, "modify")
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    run = implement(
        repository, args.id, run_tests_enabled=not args.no_tests
    )
    print(run.describe())
    if not run.ok:
        return 1

    print(f"  branch:  {run.branch} (from {run.base_branch})")
    print(f"  commit:  {(run.commit_sha or '')[:12]}")
    for path in run.files_changed[:20]:
        print(f"    {path}")
    if run.review and run.review.body:
        print()
        print(f"  {run.review.agent} review ({run.review.verdict}):")
        print("  " + run.review.body.strip().splitlines()[0][:200])
    print()
    print("Nothing has been pushed. Review the branch, then merge it yourself.")
    return 0


def cmd_show_decision(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    repository = registry.resolve(args.repository)

    for row in history(args.id):
        reason = f" — {row['reason']}" if row["reason"] else ""
        print(
            f"{row['created_at']}  {row['from_status']} -> {row['to_status']}"
            f"  ({row['actor']}){reason}"
        )
    for row in implementations_for(args.id):
        print(
            f"{row['created_at']}  implementation {row['status']}"
            f"  branch={row['branch']}  tests="
            f"{'passed' if row['tests_passed'] else 'failed/none'}"
            f"  review={row['review_verdict']}"
        )
    return 0


def cmd_portfolio(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    ensure_layout()

    if args.capability:
        matches = search_capability(args.capability, registry)
        if not matches:
            print(f"Nothing in the portfolio matches {args.capability!r}.")
            return 0
        for key, users in matches.items():
            kind, _, name = key.partition(":")
            print(f"  {name:28} ({kind:10}) {', '.join(users)}")
        return 0

    snapshot = portfolio_snapshot(registry)
    text = render_portfolio(snapshot)
    written = write_portfolio(text)

    print(
        f"{len(snapshot['repositories'])} repositories, "
        f"{len(snapshot['shared'])} shared technologies, "
        f"{len(snapshot['divergence'])} divergent pins"
    )
    for path in written:
        print(f"  {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Config paths are accepted both before and after the subcommand: the
    # natural thing to type is `scan --all --registry x`, but the global form
    # is what a wrapper script will use.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", help="Path to repositories.yaml")
    common.add_argument("--policy", help="Path to tool_policy.yaml")

    parser = argparse.ArgumentParser(
        prog="alena-improve",
        parents=[common],
        description="ALENA's autonomous codebase improvement orchestrator.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan",
        parents=[common],
        help="Scan repositories and refresh intelligence",
    )
    scan.add_argument("repository", nargs="?", help="Repository id")
    scan.add_argument("--all", action="store_true", help="Every enabled repository")
    scan.add_argument(
        "--force", action="store_true", help="Scan even if nothing has changed"
    )
    scan.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip model summaries; collect structure only",
    )
    scan.set_defaults(func=cmd_scan)

    repos = sub.add_parser("repos", parents=[common], help="List declared repositories")
    repos.add_argument("--json", action="store_true")
    repos.set_defaults(func=cmd_repos)

    show = sub.add_parser("show", parents=[common], help="Show the latest scan for a repository")
    show.add_argument("repository")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    audit = sub.add_parser("audit", parents=[common], help="Recent tool invocations")
    audit.add_argument("--limit", type=int, default=25)
    audit.set_defaults(func=cmd_audit)

    where = sub.add_parser("where", parents=[common], help="Show which files and paths are in use")
    where.set_defaults(func=cmd_where)

    context = sub.add_parser(
        "context", parents=[common], help="Write the .context/ package for agents"
    )
    context.add_argument("repository", nargs="?")
    context.add_argument("--all", action="store_true")
    context.set_defaults(func=cmd_context)

    ingest = sub.add_parser(
        "ingest-research",
        parents=[common],
        help="Ingest an external research document",
    )
    ingest.add_argument("repository")
    ingest.add_argument("path", nargs="?", help="Markdown file to ingest")
    ingest.add_argument("--from-dir", help="Ingest every markdown file in a directory")
    ingest.add_argument("--source", default="chatgpt-work")
    ingest.set_defaults(func=cmd_ingest_research)

    review = sub.add_parser(
        "review", parents=[common], help="Run engineering review over new observations"
    )
    review.add_argument("repository", nargs="?")
    review.add_argument("--all", action="store_true")
    review.add_argument("--limit", type=int, help="Review at most this many")
    review.add_argument(
        "--agent",
        choices=("codex", "claude"),
        default="codex",
        help="codex reviews everything new; claude only what clears the "
        "escalation thresholds",
    )
    review.add_argument(
        "--dry-run",
        action="store_true",
        help="With --agent claude: show what would escalate, and why, "
        "without calling the routine",
    )
    review.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-attempt escalations whose previous review errored",
    )
    review.set_defaults(func=cmd_review)

    recommend = sub.add_parser(
        "recommend", parents=[common], help="Score reviews and write the report"
    )
    recommend.add_argument("repository", nargs="?")
    recommend.add_argument("--all", action="store_true")
    recommend.set_defaults(func=cmd_recommend)

    pending = sub.add_parser(
        "pending", parents=[common], help="Recommendations awaiting a decision"
    )
    pending.add_argument("repository", nargs="?")
    pending.add_argument("--all", action="store_true")
    pending.add_argument("--status", default=RECOMMENDED)
    pending.set_defaults(func=cmd_pending)

    decide_cmd = sub.add_parser(
        "decide", parents=[common], help="Record a decision on a recommendation"
    )
    decide_cmd.add_argument("repository")
    decide_cmd.add_argument("id", type=int)
    decide_cmd.add_argument("--accept", action="store_true")
    decide_cmd.add_argument("--reject", action="store_true")
    decide_cmd.add_argument("--revisit", action="store_true", help="Reopen a rejection")
    decide_cmd.add_argument("--abandon", action="store_true")
    decide_cmd.add_argument("--successful", action="store_true")
    decide_cmd.add_argument("--unsuccessful", action="store_true")
    decide_cmd.add_argument("--reason", help="Required when rejecting or abandoning")
    decide_cmd.add_argument("--actor", default="human")
    decide_cmd.add_argument("--actual-effort", choices=("SMALL", "MEDIUM", "LARGE"))
    decide_cmd.add_argument("--observed-value", type=float)
    decide_cmd.add_argument("--feedback")
    decide_cmd.set_defaults(func=cmd_decide)

    impl = sub.add_parser(
        "implement",
        parents=[common],
        help="Implement an accepted recommendation on a branch",
    )
    impl.add_argument("repository")
    impl.add_argument("id", type=int)
    impl.add_argument("--no-tests", action="store_true", help="Skip the test run")
    impl.set_defaults(func=cmd_implement)

    trail = sub.add_parser(
        "trail", parents=[common], help="Decision and implementation history"
    )
    trail.add_argument("repository")
    trail.add_argument("id", type=int)
    trail.set_defaults(func=cmd_show_decision)

    portfolio = sub.add_parser(
        "portfolio", parents=[common], help="What the repositories have in common"
    )
    portfolio.add_argument(
        "--capability", help="Which repositories already use this technology"
    )
    portfolio.set_defaults(func=cmd_portfolio)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
