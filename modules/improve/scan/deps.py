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
    project = data.get("project", {}) or {}

    for entry in project.get("dependencies", []) or []:
        if isinstance(entry, str):
            found.extend(_parse_requirements(entry, manifest))

    # Optional groups are declared dependencies too. Skipping them loses every
    # test and lint tool, which is exactly what a "what does this project use"
    # question wants to know about.
    for entries in (project.get("optional-dependencies", {}) or {}).values():
        for entry in entries or []:
            if isinstance(entry, str):
                found.extend(_parse_requirements(entry, manifest))

    # Poetry keeps its dependencies somewhere else entirely.
    poetry = data.get("tool", {}).get("poetry", {}) or {}
    groups = [poetry.get("dependencies", {}) or {}]
    for group in (poetry.get("group", {}) or {}).values():
        groups.append((group or {}).get("dependencies", {}) or {})

    for table in groups:
        for name, spec in table.items():
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


_GO_REQUIRE_LINE = re.compile(
    r"^\s*(?P<name>[^\s()]+/[^\s()]+)\s+(?P<version>v[^\s]+)"
)


def _parse_go_mod(text: str, manifest: str) -> List[Dependency]:
    """Direct requirements from a go.mod.

    Indirect requirements are skipped: they are resolved transitively and
    listing them would bury the handful of modules the project actually chose.
    """
    found: List[Dependency] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//")[0].rstrip()
        indirect = "// indirect" in raw

        if in_block:
            if line.strip() == ")":
                in_block = False
                continue
        elif line.strip().startswith("require ("):
            in_block = True
            continue
        elif line.strip().startswith("require "):
            line = line.strip()[len("require ") :]
        else:
            continue

        match = _GO_REQUIRE_LINE.match(line)
        if match and not indirect:
            found.append(
                Dependency(match.group("name"), match.group("version"), manifest, "go")
            )
    return found


_PARSERS = {
    "requirements.txt": _parse_requirements,
    "pyproject.toml": _parse_pyproject,
    "package.json": _parse_package_json,
    "go.mod": _parse_go_mod,
}


def _parser_for(filename: str):
    """Pick a parser for a manifest filename.

    `requirements*.txt` is matched by shape rather than by exact name:
    requirements-dev.txt and requirements-test.txt are as much a declaration of
    what a project uses as requirements.txt is.
    """
    parser = _PARSERS.get(filename)
    if parser is not None:
        return parser
    if filename.startswith("requirements") and filename.endswith(".txt"):
        return _parse_requirements
    return None


def extract_dependencies(
    workspace: Path, tracked_files: List[str]
) -> List[Dependency]:
    """Parse every manifest the repository tracks.

    Driven by the tracked file list rather than a directory walk, so vendored
    copies under node_modules or .venv never turn up as project dependencies.
    """
    found: List[Dependency] = []
    for relative in tracked_files:
        parser = _parser_for(Path(relative).name)
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
