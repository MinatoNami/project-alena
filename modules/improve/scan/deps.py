"""Dependency and language extraction.

Deliberately shallow: it reads manifests, it does not resolve or install
anything. The point is to know what a repository declares, so research can be
pointed at the right ecosystem and so `dependency.outdated` has something to
compare against later.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:  # tomllib is stdlib from 3.11; pyproject parsing degrades without it
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    tomllib = None

# A requirement line, minus environment markers and extras.
_REQUIREMENT = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*"
    r"(?P<spec>[<>=!~][^;#]*)?"
)

_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".vue": "Vue",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".sh": "Shell",
    ".sql": "SQL",
}


@dataclass(frozen=True)
class Dependency:
    name: str
    specifier: Optional[str]
    manifest: str
    ecosystem: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "specifier": self.specifier,
            "manifest": self.manifest,
            "ecosystem": self.ecosystem,
        }


def _parse_requirements(text: str, manifest: str) -> List[Dependency]:
    found: List[Dependency] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            continue
        specifier = (match.group("spec") or "").strip() or None
        found.append(
            Dependency(match.group("name"), specifier, manifest, "python")
        )
    return found


def _parse_pyproject(text: str, manifest: str) -> List[Dependency]:
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(text)
    except Exception:
        return []

    found: List[Dependency] = []
    for entry in data.get("project", {}).get("dependencies", []) or []:
        if isinstance(entry, str):
            found.extend(_parse_requirements(entry, manifest))

    # Poetry keeps its dependencies somewhere else entirely.
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        found.append(
            Dependency(
                name,
                spec if isinstance(spec, str) else None,
                manifest,
                "python",
            )
        )
    return found


def _parse_package_json(text: str, manifest: str) -> List[Dependency]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    found: List[Dependency] = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            found.append(
                Dependency(name, spec if isinstance(spec, str) else None, manifest, "npm")
            )
    return found


_PARSERS = {
    "requirements.txt": _parse_requirements,
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
}


def extract_dependencies(
    workspace: Path, tracked_files: List[str]
) -> List[Dependency]:
    """Parse every manifest the repository tracks.

    Driven by the tracked file list rather than a directory walk, so vendored
    copies under node_modules or .venv never turn up as project dependencies.
    """
    found: List[Dependency] = []
    for relative in tracked_files:
        parser = _PARSERS.get(Path(relative).name)
        if parser is None:
            continue
        path = workspace / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.extend(parser(text, relative))

    # A dependency declared in two manifests is one dependency.
    seen = {}
    for dependency in found:
        seen.setdefault((dependency.ecosystem, dependency.name), dependency)
    return [seen[key] for key in sorted(seen)]


def detect_languages(tracked_files: List[str]) -> Dict[str, int]:
    """File counts per language, most common first."""
    counts: Dict[str, int] = {}
    for relative in tracked_files:
        language = _LANGUAGE_BY_SUFFIX.get(Path(relative).suffix.lower())
        if language:
            counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
