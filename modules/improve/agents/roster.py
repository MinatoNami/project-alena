"""Which agent does which segment of the loop, and which of those are real.

The pipeline has four segments that could each be done by a different model:
scanning a repository, researching it, reviewing what turned up, and acting on
a decision. Until now three of the four were hardwired -- the local model
summarised scans, Codex reviewed, Codex implemented -- and only `review` took
an `--agent` flag.

Making the other three configurable is mostly plumbing. What is *not* plumbing
is that the segments are not equally reachable by every agent, and the reasons
are structural rather than missing code:

* **Acting needs a local write path.** The action agent runs a tool on this
  machine, through the gateway, against a workspace on this disk. An agent
  reached over HTTP can read a diff and judge it; it cannot commit to a
  checkout here. Codex can because the Codex CLI runs locally.
* **`chatgpt-work` is not an agent at this end at all.** It is the *source*
  label on a research document somebody dropped into the research directory.
  There is no client, no endpoint and no invocation -- it produces documents on
  its own schedule and ALENA reads them. Assigning it a segment would be
  assigning work to something that cannot be called.

So this module is a capability matrix, not a preference list. A configuration
that asks for something unreachable is refused when it is loaded, with the
reason, rather than at 02:00 with nobody watching. Closing a gap means writing
the adapter and moving the segment from `gaps` to `segments` -- the config
surface does not change, and neither does anything that reads it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional

SCAN = "scan"
RESEARCH = "research"
REVIEW = "review"
ACTION = "action"

SEGMENTS = (SCAN, RESEARCH, REVIEW, ACTION)

SEGMENT_LABELS = {
    SCAN: "Scan: read the repository and describe what it is",
    RESEARCH: "Research: turn a repository into observations worth reviewing",
    REVIEW: "Review: judge an observation and score it",
    ACTION: "Action: implement an accepted recommendation on a branch",
}


@dataclass(frozen=True)
class Agent:
    """One model ALENA can hand a segment to.

    `segments` is what is wired today. `gaps` is every other segment with the
    reason it cannot have it, because "unsupported" on its own tells whoever
    reads the error nothing about whether it is a missing adapter or a
    structural impossibility.
    """

    name: str
    description: str
    reach: str
    segments: FrozenSet[str] = frozenset()
    gaps: Mapping[str, str] = field(default_factory=dict)

    def can(self, segment: str) -> bool:
        return segment in self.segments

    def why_not(self, segment: str) -> str:
        if segment not in SEGMENTS:
            return f"{segment!r} is not a segment of the loop"
        return self.gaps.get(segment, f"{self.name} does not do {segment}")


AGENTS: Dict[str, Agent] = {
    agent.name: agent
    for agent in [
        Agent(
            name="local",
            description="Whatever LM Studio has loaded, through the Tool Gateway",
            reach="local",
            segments=frozenset({SCAN, RESEARCH}),
            gaps={
                REVIEW: (
                    "not wired. A review has to return a scored verdict this "
                    "pipeline can parse, and only the Codex and Claude prompts "
                    "produce one today"
                ),
                ACTION: (
                    "not wired. It has a local write path in principle -- "
                    "codex_edit through the gateway -- but nothing routes an "
                    "accepted recommendation to it"
                ),
            },
        ),
        Agent(
            name="codex",
            description="Codex CLI, run locally as an MCP server",
            reach="local",
            segments=frozenset({REVIEW, ACTION}),
            gaps={
                SCAN: (
                    "not wired. A scan summary is a short description, and "
                    "spending a Codex call on one buys nothing the local model "
                    "does not already do for free"
                ),
                RESEARCH: (
                    "not wired. The local agent does this through alena-core's "
                    "read-only tools; a Codex investigation would cost a call "
                    "per repository per night for the same reading"
                ),
            },
        ),
        Agent(
            name="claude",
            description="A Claude Code Routine, over HTTP",
            reach="hosted",
            segments=frozenset({REVIEW}),
            gaps={
                SCAN: "not wired; the adapter exists for review only",
                RESEARCH: "not wired; the adapter exists for review only",
                ACTION: (
                    "structural: a routine runs on Anthropic's side and cannot "
                    "write to a checkout on this machine. It can review a diff "
                    "that something local produced"
                ),
            },
        ),
        Agent(
            name="chatgpt-work",
            description="Research documents, delivered on its own schedule",
            reach="none",
            segments=frozenset(),
            gaps={
                segment: (
                    "structural: chatgpt-work is a source label on a document "
                    "somebody dropped in the research directory, not something "
                    "ALENA can call. There is no endpoint to invoke"
                )
                for segment in SEGMENTS
            },
        ),
    ]
}

# What runs when nothing is configured: exactly today's behaviour.
DEFAULTS: Dict[str, str] = {
    SCAN: "local",
    RESEARCH: "chatgpt-work",
    REVIEW: "codex",
    ACTION: "codex",
}


class RosterError(ValueError):
    """The requested assignment cannot be honoured."""


@dataclass(frozen=True)
class Assignment:
    """Who does what, for one run."""

    segments: Mapping[str, str]

    def agent_for(self, segment: str) -> str:
        if segment not in SEGMENTS:
            raise RosterError(f"{segment!r} is not a segment of the loop")
        return self.segments[segment]

    def describe(self) -> str:
        return "  ".join(f"{s}={self.segments[s]}" for s in SEGMENTS)


def resolve(
    requested: Optional[Mapping[str, str]] = None,
    *,
    allow_unreachable: Iterable[str] = (RESEARCH,),
) -> Assignment:
    """Fill in the defaults and refuse anything that cannot actually run.

    `research` is exempt, and this is the one asymmetry worth stating: its
    default is `chatgpt-work`, which by construction ALENA cannot invoke. That
    is not a broken configuration -- it is how research works today. Documents
    arrive, the cycle ingests them. So an unreachable research agent is
    allowed, and every other segment must name an agent that can be called.
    """
    resolved = dict(DEFAULTS)
    for segment, agent_name in (requested or {}).items():
        if segment not in SEGMENTS:
            known = ", ".join(SEGMENTS)
            raise RosterError(f"Unknown segment {segment!r}. Segments are: {known}")
        if agent_name not in AGENTS:
            known = ", ".join(sorted(AGENTS))
            raise RosterError(
                f"Unknown agent {agent_name!r} for {segment}. Agents are: {known}"
            )
        resolved[segment] = agent_name

    for segment, agent_name in resolved.items():
        if segment in allow_unreachable:
            continue
        agent = AGENTS[agent_name]
        if not agent.can(segment):
            capable = [name for name, a in sorted(AGENTS.items()) if a.can(segment)]
            raise RosterError(
                f"{agent_name} cannot do {segment}: {agent.why_not(segment)}. "
                f"Agents that can: {', '.join(capable) or 'none yet'}"
            )

    return Assignment(segments=resolved)


def matrix() -> Dict[str, Dict[str, Optional[str]]]:
    """The whole picture: agent -> segment -> None if it can, else the reason.

    Shaped for printing and for the dashboard, so both show the same thing
    without either deciding for itself what is possible.
    """
    return {
        name: {
            segment: None if agent.can(segment) else agent.why_not(segment)
            for segment in SEGMENTS
        }
        for name, agent in AGENTS.items()
    }


DEFAULT_CONFIG = "config/agents.yaml"


def config_path(path: Optional[str] = None) -> Path:
    """Where the assignment is read from. Relative paths resolve to the root."""
    raw = path or os.getenv("ALENA_AGENTS") or DEFAULT_CONFIG
    resolved = Path(raw).expanduser()
    if resolved.is_absolute():
        return resolved
    return Path(__file__).resolve().parents[3] / resolved


def parse(document: Any) -> Assignment:
    """Read the `segments:` mapping out of a loaded YAML document."""
    if document is None:
        return resolve()
    if not isinstance(document, dict):
        raise RosterError("The agents file must be a mapping")

    requested = document.get("segments") or {}
    if not isinstance(requested, dict):
        raise RosterError("`segments:` must be a mapping of segment to agent")
    return resolve({str(k): str(v) for k, v in requested.items()})


def load(path: Optional[str] = None) -> Assignment:
    """The configured assignment, or the defaults when there is no file.

    Unlike the tool policy, a missing file here is not an error. The defaults
    are exactly what ran before this was configurable, so the absence of the
    file means "keep doing what you were doing" rather than "deny everything".
    """
    import yaml

    resolved = config_path(path)
    if not resolved.exists():
        return resolve()
    return parse(yaml.safe_load(resolved.read_text()))
