"""TODO / FIXME extraction and diffing between runs.

The interesting signal is not the count, it is the delta: a TODO that appeared
this week is a lead, and one that disappeared is evidence something got done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

MARKERS = ("TODO", "FIXME", "HACK", "XXX")

# git grep -n output: path:line:text
_GREP_LINE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+):(?P<text>.*)$")
_MARKER = re.compile(rf"\b(?P<marker>{'|'.join(MARKERS)})\b[:\s]?(?P<note>.*)")


@dataclass(frozen=True)
class Todo:
    path: str
    line: int
    marker: str
    text: str

    @property
    def key(self) -> str:
        """Identity for diffing.

        Deliberately excludes the line number: a TODO that moved because
        something above it changed is the same TODO, and counting it as
        resolved-and-reintroduced every time would drown the real signal.
        """
        return f"{self.path}::{self.marker}::{self.text.strip()}"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "marker": self.marker,
            "text": self.text,
        }


def parse_grep(lines: Sequence[str]) -> List[Todo]:
    todos: List[Todo] = []
    for raw in lines:
        match = _GREP_LINE.match(raw)
        if not match:
            continue
        marker_match = _MARKER.search(match.group("text"))
        if not marker_match:
            continue
        todos.append(
            Todo(
                path=match.group("path"),
                line=int(match.group("line")),
                marker=marker_match.group("marker"),
                text=marker_match.group("note").strip()[:200],
            )
        )
    return todos


def diff_todos(
    current: Sequence[Todo], previous: Sequence[dict]
) -> Dict[str, List[dict]]:
    """What appeared and what went away since the previous scan."""
    previous_todos = [
        Todo(
            path=item.get("path", ""),
            line=int(item.get("line", 0)),
            marker=item.get("marker", ""),
            text=item.get("text", ""),
        )
        for item in previous
    ]
    current_keys = {todo.key for todo in current}
    previous_keys = {todo.key for todo in previous_todos}

    return {
        "added": [t.to_dict() for t in current if t.key not in previous_keys],
        "resolved": [
            t.to_dict() for t in previous_todos if t.key not in current_keys
        ],
    }
