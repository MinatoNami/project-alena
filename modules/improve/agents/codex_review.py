"""Codex engineering review.

The spec has Codex triggered by its own Automation system. It is driven
directly here instead, through the Codex CLI the repo already wires up as an
MCP server: synchronous, testable, and it works without depending on a
provider-side scheduler to have run.

Codex answers one question: *given the actual implementation, does this
recommendation make engineering sense?* It does not implement anything, and it
structurally cannot -- the review runs as agent `codex`, and the tool policy
grants that identity read-only tools only. `codex_edit` is not on its list.
That is the enforcement; the prompt below merely agrees with it.

## The observation is untrusted input

Research text is written by an external agent reading the public internet. It
reaches a coding agent, which makes it a prompt-injection path. Three things
hold it in place:

1. The gateway. Even a fully hijacked review cannot call a tool that writes,
   because the policy is keyed on the agent identity, not on the prompt.
2. Framing. The observation is delimited and labelled as third-party data, and
   the instruction to ignore instructions inside it comes *before* the data.
3. `repo_path` comes from the registry, never from the document.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.core.controller.logger import logger
from modules.gateway.errors import GatewayDenied

from .prompting import (
    VERDICT_SCHEMA,
    observation_block,
    operator_note,
    preamble_for,
    priors_block,
)

AGENT = "codex"
VERDICTS = ("supported", "rejected", "unclear")

_FENCE = re.compile(r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"(?P<body>\{[^{}]*\"verdict\".*?\})", re.DOTALL)


@dataclass(frozen=True)
class ReviewResult:
    observation_id: int
    verdict: str
    body: str
    confidence: Optional[float] = None
    fit: Optional[float] = None
    cost: Optional[float] = None
    risk: Optional[float] = None
    value: Optional[float] = None
    requires_architecture_review: bool = False
    # Tri-state: None means the reviewer did not say, which is the only case
    # where the repository's domain tags decide. See agents/triggers.py.
    security_sensitive: Optional[bool] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def build_prompt(
    repository_name: str,
    observation: Dict[str, Any],
    context: Optional[str] = None,
    priors: Optional[List[Dict[str, Any]]] = None,
    note: Optional[str] = None,
) -> str:
    return f"""You are reviewing a proposal against the repository you are
running inside. Decide whether it makes engineering sense *here*.

{preamble_for(observation.get("source"))}

Do not modify anything. This is a read-only review.
{operator_note(note)}{priors_block(priors)}
Repository: {repository_name}
{f"Context:{chr(10)}{context}{chr(10)}" if context else ""}
{observation_block(observation)}

Inspect the repository and answer. Cover: whether the capability already
exists, which modules would change, what the migration and data implications
are, and what could go wrong.

End your answer with a fenced JSON block, and nothing after it:

{VERDICT_SCHEMA}"""


def parse_verdict(text: str) -> Dict[str, Any]:
    """Pull the JSON block out of a Codex answer.

    A review whose prose is useful but whose JSON is malformed is still worth
    keeping, so a parse failure yields "unclear" rather than an error -- the
    body is retained either way and a human can read it.
    """
    for pattern in (_FENCE, _BARE):
        for match in reversed(list(pattern.finditer(text or ""))):
            try:
                payload = json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "verdict" in payload:
                verdict = str(payload.get("verdict", "")).strip().lower()
                payload["verdict"] = verdict if verdict in VERDICTS else "unclear"
                return payload
    return {"verdict": "unclear"}


async def review_observation(
    repository,
    observation: Dict[str, Any],
    *,
    context: Optional[str] = None,
    priors: Optional[List[Dict[str, Any]]] = None,
    note: Optional[str] = None,
    executor=None,
) -> ReviewResult:
    """Ask Codex about one observation, through the gateway."""
    from modules.core.controller.agent import _get_server_for_tool
    from modules.core.controller.normalize import normalize_codex_output
    from modules.core.controller.tool_executor import execute_tool

    executor = executor or execute_tool
    prompt = build_prompt(repository.name, observation, context, priors, note)

    try:
        raw = await executor(
            _get_server_for_tool("codex_analyze"),
            "codex_analyze",
            # repo_path comes from the registry. Never from the document.
            {"repo_path": str(repository.workspace), "question": prompt},
            agent=AGENT,
            repository_id=repository.id,
        )
    except GatewayDenied as exc:
        logger.warning(f"Codex review refused for {repository.id}: {exc}")
        return ReviewResult(
            observation["id"], verdict="error", body="", error=f"refused: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - one bad review is not a failed run
        logger.warning(f"Codex review failed for {repository.id}: {exc!r}")
        return ReviewResult(
            observation["id"],
            verdict="error",
            body="",
            error=f"{type(exc).__name__}: {exc}",
        )

    content = getattr(raw, "content", raw)
    body = normalize_codex_output(content)["message"] if content else ""
    payload = parse_verdict(body)

    def number(key: str) -> Optional[float]:
        value = payload.get(key)
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return None

    return ReviewResult(
        observation_id=observation["id"],
        verdict=payload["verdict"],
        body=body,
        confidence=number("confidence"),
        fit=number("fit"),
        cost=number("cost"),
        risk=number("risk"),
        value=number("value"),
        requires_architecture_review=bool(payload.get("requires_architecture_review")),
        security_sensitive=payload.get("security_sensitive"),
    )
