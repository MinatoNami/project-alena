"""Tool effectiveness, computed from the audit log.

The addendum wants tools measured so an unused one can be retired and a
failing one can be flagged for repair. Everything needed has been recorded
since the gateway went in: every invocation, allowed or refused, with its
outcome, duration and arguments hash.

Two of the addendum's dimensions are **not** measured here, and pretending
otherwise would be worse than the gap:

* **Token savings.** Knowing that `django.extract_api` saved 5,000 tokens
  means comparing against the reconstruction it replaced, and nothing records
  what an agent would have done instead.
* **Accuracy.** A tool returning something wrong looks exactly like a tool
  returning something right. Only an agent's later behaviour distinguishes
  them, and that is not attributed back.

So the utility score below is about *use and reliability*, not value. It
answers "is this tool earning its place in the catalog", not "is this tool
good".

The refusal rate is the one to watch. An agent repeatedly reaching for a
capability the policy will not give it is the signal the tool-proposal
lifecycle is meant to act on -- it means the catalog is missing something, or
the policy is wrong about who should have it.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from modules.store import get_connection

# A repeat of the same tool with the same arguments inside this window is
# treated as a retry rather than as a second piece of work.
RETRY_WINDOW_SECONDS = 300

FAILING_RATE = 0.25
CONTESTED_RATE = 0.25

# How much history has to exist before "nothing has called this" means
# anything. Advising someone to retire a tool because a young audit log has
# not seen it yet is worse than saying nothing: it is confident and wrong.
MIN_INVOCATIONS_TO_JUDGE = 20
MIN_DAYS_TO_JUDGE = 7

HEALTHY = "healthy"
UNUSED = "unused"
UNPROVEN = "unproven"
FAILING = "failing"
CONTESTED = "contested"


@dataclass
class ToolMetrics:
    tool: str
    invocations: int = 0
    successes: int = 0
    failures: int = 0
    denials: int = 0
    retries: int = 0
    repositories: int = 0
    agents: List[str] = field(default_factory=list)
    median_ms: Optional[float] = None
    slowest_ms: Optional[int] = None
    last_used: Optional[str] = None
    declared: bool = True
    # Whether the audit log is substantial enough to draw a conclusion from
    # this tool's absence. Set once for the whole catalog, not per tool.
    judgeable: bool = True

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def reliability(self) -> Optional[float]:
        """Successes as a share of calls that actually reached the tool."""
        if not self.attempts:
            return None
        return self.successes / self.attempts

    @property
    def refusal_rate(self) -> float:
        if not self.invocations:
            return 0.0
        return self.denials / self.invocations

    @property
    def retry_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return self.retries / self.attempts

    @property
    def health(self) -> str:
        if not self.invocations:
            return UNUSED if self.judgeable else UNPROVEN
        if self.refusal_rate >= CONTESTED_RATE:
            return CONTESTED
        if self.reliability is not None and self.reliability < (1 - FAILING_RATE):
            return FAILING
        return HEALTHY

    @property
    def utility(self) -> float:
        """A rough "is this earning its place" score, 0 to 1.

        Deliberately crude. It is a sort order for a human reading a list, not
        an input to an automatic decision -- nothing retires a tool on the
        strength of this number.
        """
        if not self.invocations:
            return 0.0
        # Usage saturates: the difference between 50 calls and 500 does not
        # matter nearly as much as the difference between 0 and 5.
        usage = min(self.invocations, 20) / 20
        reliability = self.reliability if self.reliability is not None else 0.0
        reach = min(self.repositories, 3) / 3
        friction = min(self.retry_rate, 1.0)
        return round(
            0.4 * usage + 0.4 * reliability + 0.2 * reach - 0.2 * friction, 4
        )

    def advice(self) -> Optional[str]:
        if self.health == UNPROVEN:
            return None
        if self.health == UNUSED:
            return (
                "never called. Retire it, or find out why nothing reaches for it."
            )
        if self.health == CONTESTED:
            return (
                f"{self.denials} of {self.invocations} calls were refused. Either "
                "the policy is wrong about who should have this, or agents are "
                "reaching for a capability the catalog does not offer."
            )
        if self.health == FAILING:
            return (
                f"{self.failures} of {self.attempts} calls failed. Flag it for "
                "repair before something depends on it."
            )
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "health": self.health,
            "utility": self.utility,
            "invocations": self.invocations,
            "successes": self.successes,
            "failures": self.failures,
            "denials": self.denials,
            "retries": self.retries,
            "repositories": self.repositories,
            "agents": self.agents,
            "median_ms": self.median_ms,
            "slowest_ms": self.slowest_ms,
            "last_used": self.last_used,
            "declared": self.declared,
        }


def _count_retries(rows: List[sqlite3.Row]) -> int:
    """Repeats of the same arguments close together.

    An agent that calls the same tool the same way twice in five minutes did
    not want two answers; the first one did not work for it.
    """
    from datetime import datetime

    seen: Dict[str, Any] = {}
    retries = 0
    for row in rows:
        key = row["arguments_hash"]
        try:
            when = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            continue
        previous = seen.get(key)
        if previous is not None and (when - previous).total_seconds() <= RETRY_WINDOW_SECONDS:
            retries += 1
        seen[key] = when
    return retries


def _is_judgeable(by_tool: Dict[str, List[sqlite3.Row]]) -> bool:
    """Is there enough history for an absence to mean something?

    Both conditions, and conservatively: enough calls to have exercised the
    catalog, over enough days to have covered the weekly cadence the system
    runs on. A busy afternoon is not evidence that the weekly research tools
    are dead.
    """
    from datetime import datetime

    rows = [row for rows in by_tool.values() for row in rows]
    if len(rows) < MIN_INVOCATIONS_TO_JUDGE:
        return False

    stamps = []
    for row in rows:
        try:
            stamps.append(datetime.fromisoformat(row["created_at"]))
        except (TypeError, ValueError):
            continue
    if not stamps:
        return False
    return (max(stamps) - min(stamps)).days >= MIN_DAYS_TO_JUDGE


def audit_basis(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """What the metrics are being computed from."""
    from datetime import datetime

    conn = conn or get_connection()
    rows = list(conn.execute("SELECT created_at FROM tool_invocations ORDER BY id"))
    if not rows:
        return {"invocations": 0, "days": 0, "judgeable": False}

    stamps = []
    for row in rows:
        try:
            stamps.append(datetime.fromisoformat(row["created_at"]))
        except (TypeError, ValueError):
            continue
    days = (max(stamps) - min(stamps)).days if stamps else 0
    return {
        "invocations": len(rows),
        "days": days,
        "judgeable": len(rows) >= MIN_INVOCATIONS_TO_JUDGE
        and days >= MIN_DAYS_TO_JUDGE,
    }


def tool_metrics(
    catalog=None, conn: Optional[sqlite3.Connection] = None
) -> List[ToolMetrics]:
    """Metrics for every tool, including ones that have never been called.

    Tools with no invocations are the point of including them: a catalog entry
    nothing reaches for is the first thing the addendum says to retire.
    """
    conn = conn or get_connection()

    by_tool: Dict[str, List[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM tool_invocations ORDER BY id"):
        by_tool.setdefault(row["tool"], []).append(row)

    known = set(catalog.names()) if catalog is not None else set()
    judgeable = _is_judgeable(by_tool)
    metrics: List[ToolMetrics] = []

    for tool in sorted(known | set(by_tool)):
        rows = by_tool.get(tool, [])
        durations = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
        entry = ToolMetrics(
            tool=tool,
            invocations=len(rows),
            successes=sum(1 for r in rows if r["outcome"] == "success"),
            failures=sum(1 for r in rows if r["outcome"] == "error"),
            denials=sum(1 for r in rows if r["outcome"] == "denied"),
            retries=_count_retries([r for r in rows if r["outcome"] != "denied"]),
            repositories=len({r["repository_id"] for r in rows if r["repository_id"]}),
            agents=sorted({r["agent"] for r in rows}),
            median_ms=round(statistics.median(durations), 1) if durations else None,
            slowest_ms=max(durations) if durations else None,
            last_used=rows[-1]["created_at"] if rows else None,
            declared=tool in known if catalog is not None else True,
            judgeable=judgeable,
        )
        metrics.append(entry)

    return sorted(metrics, key=lambda m: (-m.utility, m.tool))


def needing_attention(metrics: List[ToolMetrics]) -> List[ToolMetrics]:
    return [m for m in metrics if m.health != HEALTHY]
