"""Portfolio intelligence: what the repositories have in common.

The spec's ambition for this is a system that notices Text Whisperer already
has transcription before the health app grows its own. That needs semantic
understanding of what each repository *does*, which is a later problem.

What is available now is deterministic and still useful: every repository has
been scanned, so their languages, declared dependencies and registry tags are
known facts. Three things fall out of comparing them.

* **Shared technology.** Which repositories would be affected by the same
  framework release, and which are alone on something.
* **Divergent versions.** The same dependency pinned differently in two
  places. Nobody decided that; it accumulated.
* **Findings that travel.** A recommendation accepted for one repository, in a
  technology another repository also uses.

None of this is written into the recommendations table. A cross-repository
finding is an observation for a human to look at, and turning one into a
recommendation automatically would let it skip the review pipeline everything
else goes through.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

# Dependencies too common to say anything by being shared.
UBIQUITOUS = frozenset(
    {
        "typescript", "eslint", "prettier", "vite", "pytest", "ruff", "mypy",
        "black", "flake8", "vue", "vue-router", "@types/node",
    }
)

MIN_SHARED = 2

_VERSION = re.compile(r"^\d+(?:\.\d+)*$")


def _normalise_version(token: str) -> str:
    """Trim trailing zero components: 23.0 and 23 are the same pin.

    Only trailing zeros, and only whole components -- 0.10 keeps its 10.
    """
    if not _VERSION.match(token):
        return token
    parts = token.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def normalise_specifier(specifier: Optional[str]) -> Optional[str]:
    """A comparable form of a version specifier.

    `>=23.0,<24.0` and `>=23,<24` are the same constraint written twice, and
    reporting them as a divergence buries the ones that are real.
    """
    if not specifier:
        return None
    clauses = []
    for clause in specifier.replace(" ", "").split(","):
        if not clause:
            continue
        operator = "".join(c for c in clause if not (c.isdigit() or c == "."))
        version = clause[len(operator):] if clause.startswith(operator) else clause
        clauses.append(f"{operator}{_normalise_version(version)}")
    return ",".join(sorted(clauses)) or None


@dataclass(frozen=True)
class Technology:
    """Something a repository uses: a language, a dependency, or a tag."""

    name: str
    kind: str  # language | dependency | tag

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"


@dataclass
class CapabilityGraph:
    """Repositories and the technologies they share.

    The addendum draws this as a tree per repository; stored as edges because
    the useful direction is the other one -- given a technology, who uses it.
    """

    repositories: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: Dict[str, set] = field(default_factory=lambda: defaultdict(set))

    def add(self, repository_id: str, technology: Technology) -> None:
        self.edges[technology.key].add(repository_id)

    def users_of(self, technology_key: str) -> List[str]:
        return sorted(self.edges.get(technology_key, ()))

    def technologies_of(self, repository_id: str) -> List[str]:
        return sorted(
            key for key, users in self.edges.items() if repository_id in users
        )

    def shared(self, minimum: int = MIN_SHARED) -> Dict[str, List[str]]:
        """Technologies used by at least `minimum` repositories."""
        return {
            key: sorted(users)
            for key, users in sorted(self.edges.items())
            if len(users) >= minimum
        }

    def unique_to(self, repository_id: str) -> List[str]:
        """Technologies only this repository uses.

        Where a capability worth sharing tends to live, and also where a
        one-off dependency nobody else validated tends to live.
        """
        return sorted(
            key
            for key, users in self.edges.items()
            if users == {repository_id}
        )

    def search(self, term: str) -> Dict[str, List[str]]:
        """Which repositories use anything matching `term`."""
        needle = term.strip().lower()
        if not needle:
            return {}
        return {
            key: sorted(users)
            for key, users in sorted(self.edges.items())
            if needle in key.lower()
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repositories": {
                repo_id: {
                    "name": info.get("name", repo_id),
                    "technologies": self.technologies_of(repo_id),
                }
                for repo_id, info in sorted(self.repositories.items())
            },
            "shared": self.shared(),
        }


def build_graph(
    repositories: Sequence[Any], scans: Dict[str, Optional[Dict[str, Any]]]
) -> CapabilityGraph:
    """Build the graph from the registry and the latest scan of each repository."""
    graph = CapabilityGraph()

    for repository in repositories:
        scan = scans.get(repository.id) or {}
        graph.repositories[repository.id] = {
            "name": repository.name,
            "tags": list(repository.tags),
            "scanned": bool(scan),
        }

        for tag in repository.tags:
            graph.add(repository.id, Technology(tag.lower(), "tag"))
        for language in (scan.get("languages") or {}):
            graph.add(repository.id, Technology(language.lower(), "language"))
        for dependency in scan.get("dependencies") or []:
            name = str(dependency.get("name", "")).lower()
            if name and name not in UBIQUITOUS:
                graph.add(repository.id, Technology(name, "dependency"))

    return graph


@dataclass(frozen=True)
class VersionDivergence:
    name: str
    ecosystem: str
    specifiers: Dict[str, Optional[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ecosystem": self.ecosystem,
            "specifiers": dict(sorted(self.specifiers.items())),
        }

    def describe(self) -> str:
        pinned = ", ".join(
            f"{repo} {spec or 'unpinned'}"
            for repo, spec in sorted(self.specifiers.items())
        )
        return f"{self.name} ({self.ecosystem}): {pinned}"


def dependency_divergence(
    scans: Dict[str, Optional[Dict[str, Any]]]
) -> List[VersionDivergence]:
    """The same dependency, specified differently in different repositories.

    Nobody decides this; it accumulates. It is worth surfacing because the
    repositories that drift furthest apart are the ones where a shared fix
    stops applying cleanly.
    """
    seen: Dict[tuple, Dict[str, Optional[str]]] = defaultdict(dict)

    for repository_id, scan in scans.items():
        for dependency in (scan or {}).get("dependencies") or []:
            name = str(dependency.get("name", "")).lower()
            if not name or name in UBIQUITOUS:
                continue
            key = (name, dependency.get("ecosystem", "unknown"))
            seen[key][repository_id] = dependency.get("specifier")

    divergent = []
    for (name, ecosystem), specifiers in sorted(seen.items()):
        if len(specifiers) < 2:
            continue
        # Compared normalised, reported verbatim: the reader wants to see what
        # is actually written in each manifest.
        if len({normalise_specifier(value) for value in specifiers.values()}) < 2:
            continue
        divergent.append(VersionDivergence(name, ecosystem, specifiers))
    return divergent


@dataclass(frozen=True)
class PortfolioFinding:
    """An observation about the portfolio rather than about one repository."""

    kind: str
    title: str
    detail: str
    repositories: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "repositories": list(self.repositories),
        }


def travelling_recommendations(
    graph: CapabilityGraph,
    decided: Dict[str, List[Dict[str, Any]]],
) -> List[PortfolioFinding]:
    """Accepted work in a technology another repository also uses.

    Only accepted and successful ones travel. A rejection is a judgement about
    one repository's circumstances and does not transfer -- suggesting a
    neighbour adopt something you turned down is worse than saying nothing.
    """
    findings: List[PortfolioFinding] = []

    for repository_id, recommendations in sorted(decided.items()):
        technologies = set(graph.technologies_of(repository_id))
        for recommendation in recommendations:
            if recommendation.get("status") not in ("accepted", "implemented", "successful"):
                continue

            neighbours = sorted(
                {
                    other
                    for key in technologies
                    for other in graph.users_of(key)
                    if other != repository_id
                }
            )
            if not neighbours:
                continue

            findings.append(
                PortfolioFinding(
                    kind="travelling-recommendation",
                    title=recommendation["title"],
                    detail=(
                        f"{recommendation['status'].capitalize()} for "
                        f"{repository_id}. These share technology with it and "
                        "may want the same thing."
                    ),
                    repositories=[repository_id, *neighbours],
                )
            )
    return findings


def analyse(
    repositories: Sequence[Any],
    scans: Dict[str, Optional[Dict[str, Any]]],
    decided: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Everything the portfolio view knows, as plain data."""
    graph = build_graph(repositories, scans)
    divergence = dependency_divergence(scans)

    findings: List[PortfolioFinding] = [
        PortfolioFinding(
            kind="version-divergence",
            title=f"{item.name} is pinned differently across repositories",
            detail=item.describe(),
            repositories=sorted(item.specifiers),
        )
        for item in divergence
    ]
    findings += travelling_recommendations(graph, decided or {})

    return {
        "graph": graph,
        "shared": graph.shared(),
        "divergence": divergence,
        "findings": findings,
    }
