"""Parse a research document into observations.

The document comes from outside ALENA -- today, a ChatGPT Work scheduled task.
Rather than guess at arbitrary markdown, the shape is a contract:
`Documents/RESEARCH_DOCUMENT_CONTRACT.md` describes it and
`config/research-template.md` is what the scheduled task is told to produce.

Parsing degrades rather than failing. A document with no headings becomes one
observation containing the whole text, because a research report that arrives
in the wrong shape is still worth reading.

Everything parsed here is untrusted third-party text. It is stored and later
shown to a coding agent as *data*; nothing in this module treats any part of a
document as an instruction, and the reviewer prompt says so explicitly.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

from ..text import normalize_title

# `## Heading` starts an observation. `#` is the document title.
_SECTION = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
_TITLE = re.compile(r"^#\s+(?P<title>.+?)\s*$", re.MULTILINE)
_FIELD = re.compile(
    r"^\s*(?P<key>Date|Source|Repository|Evidence)\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
# Emphasis is stripped before matching a field, because both `**Evidence:** x`
# and `**Evidence**: x` are natural to write and neither parses cleanly with
# the markers left in place.
_EMPHASIS = re.compile(r"[*_]{1,3}")




def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParsedObservation:
    title: str
    body: str
    evidence: Optional[str] = None

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)

    def text(self) -> str:
        """Title and body together, for similarity comparison."""
        return f"{self.title}\n\n{self.body}".strip()


@dataclass(frozen=True)
class ParsedResearch:
    title: Optional[str]
    source: Optional[str]
    document_date: Optional[str]
    repository: Optional[str]
    observations: List[ParsedObservation]
    content: str

    @property
    def content_hash(self) -> str:
        return content_hash(self.content)


def _match_field(line: str):
    return _FIELD.match(_EMPHASIS.sub("", line))


def _fields(text: str) -> dict:
    found = {}
    for line in text.splitlines():
        match = _match_field(line)
        if match:
            found[match.group("key").lower()] = match.group("value").strip()
    return found


def _split_evidence(body: str) -> tuple[str, Optional[str]]:
    lines = body.splitlines()
    kept: List[str] = []
    evidence: List[str] = []
    for line in lines:
        match = _match_field(line)
        if match and match.group("key").lower() == "evidence":
            evidence.append(match.group("value").strip())
        else:
            kept.append(line)
    return "\n".join(kept).strip(), ("\n".join(evidence).strip() or None)


def parse_research(text: str) -> ParsedResearch:
    header_end = len(text)
    sections = list(_SECTION.finditer(text))
    if sections:
        header_end = sections[0].start()

    header = text[:header_end]
    fields = _fields(header)
    title_match = _TITLE.search(header)

    observations: List[ParsedObservation] = []
    for index, match in enumerate(sections):
        start = match.end()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        body, evidence = _split_evidence(text[start:end])
        if not body and not evidence:
            # A heading with nothing under it is a table of contents entry, not
            # an observation.
            continue
        observations.append(
            ParsedObservation(title=match.group("title"), body=body, evidence=evidence)
        )

    if not observations and text.strip():
        body, evidence = _split_evidence(text[header_end:] or text)
        observations.append(
            ParsedObservation(
                title=(title_match.group("title") if title_match else "Research"),
                body=body or text.strip(),
                evidence=evidence,
            )
        )

    return ParsedResearch(
        title=title_match.group("title") if title_match else None,
        source=fields.get("source"),
        document_date=fields.get("date"),
        repository=fields.get("repository"),
        observations=observations,
        content=text,
    )
