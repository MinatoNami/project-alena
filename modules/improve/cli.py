"""`alena-improve` -- the orchestrator's command line.

Every trigger in the spec is a subcommand here rather than a scheduler inside
the application. launchd survives reboots, a subcommand can be re-run by hand
when something looks wrong, and the same entry point is what a unit test calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence

from .artifacts import ensure_layout, intelligence_dir
from .persistence import latest_scan
from .registry import RegistryError, Repository, load_registry
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
