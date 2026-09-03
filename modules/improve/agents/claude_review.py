"""Claude Code as the independent engineering reviewer.

The point of a second reviewer is that it is a *different* model reaching its
own conclusion, so it deliberately overlaps with Codex. Its job is to answer
"is Codex's assessment actually correct?", and a disagreement is a result, not
a problem to average away.

## How it is reached

Claude Code Routines expose an HTTP trigger, which is what makes this the one
agent ALENA initiates rather than merely consumes. The client speaks a small
explicit contract:

    POST <CLAUDE_ROUTINE_URL>   {"prompt": ..., "metadata": {...}}

and accepts either a finished answer in that response, or a job to poll:

    {"result": "..."}                     -- synchronous, done
    {"status": "completed", "result": ""} -- done
    {"id": "...", "status": "running"}    -- poll <url>/<id> until terminal

Response *reading* is deliberately tolerant -- the answer text is looked for
under several common keys -- because the exact envelope depends on how the
routine is configured, and a rigid parser would fail on a working endpoint.

**This has not been run against a live routine.** The contract above is what
`CLAUDE_ROUTINE_URL` must satisfy; if the real envelope differs, `extract_text`
is the single place to adjust.

## Containment differs from Codex

Codex is contained by the Tool Gateway: it runs as an identity the policy
grants read-only tools. A routine runs on Anthropic's side and ALENA's gateway
has no say over what it can do there -- so the containment here is narrower and
worth stating plainly. ALENA sends text and parses text. The routine cannot
reach ALENA's tools, its repositories, or its database. What a routine may do
in its own environment is configured where the routine is defined, not here.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from modules.core.controller.logger import logger

from .prompting import (
    UNTRUSTED_PREAMBLE,
    VERDICT_SCHEMA,
    observation_block,
    rejected_block,
)

AGENT = "claude"

DEFAULT_TIMEOUT = 300.0
DEFAULT_POLL_INTERVAL = 5.0
TERMINAL_STATES = {"completed", "complete", "succeeded", "success", "done", "finished"}
FAILED_STATES = {"failed", "error", "errored", "cancelled", "canceled", "timeout"}

# Keys a routine might return its answer under.
_TEXT_KEYS = ("result", "output", "text", "content", "answer", "response", "message")


class RoutineError(RuntimeError):
    pass


class RoutineNotConfigured(RoutineError):
    pass


@dataclass(frozen=True)
class RoutineConfig:
    url: str
    token: Optional[str] = None
    timeout_s: float = DEFAULT_TIMEOUT
    poll_interval_s: float = DEFAULT_POLL_INTERVAL

    @classmethod
    def from_env(cls) -> "RoutineConfig":
        url = (os.getenv("CLAUDE_ROUTINE_URL") or "").strip()
        if not url:
            raise RoutineNotConfigured(
                "CLAUDE_ROUTINE_URL is not set, so there is nowhere to send a "
                "Claude review. Set it to the routine's HTTP trigger, or run "
                "review with --agent codex only."
            )
        return cls(
            url=url,
            token=(os.getenv("CLAUDE_ROUTINE_TOKEN") or "").strip() or None,
            timeout_s=float(os.getenv("CLAUDE_ROUTINE_TIMEOUT", DEFAULT_TIMEOUT)),
            poll_interval_s=float(
                os.getenv("CLAUDE_ROUTINE_POLL_INTERVAL", DEFAULT_POLL_INTERVAL)
            ),
        )


def extract_text(payload: Any) -> str:
    """Find the answer in a routine response.

    Tolerant on purpose: the envelope depends on how the routine is set up,
    and refusing to read a working endpoint over a key name helps nobody.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "\n".join(extract_text(item) for item in payload).strip()
    if not isinstance(payload, dict):
        return ""

    for key in _TEXT_KEYS:
        if key in payload:
            found = extract_text(payload[key])
            if found:
                return found
    return ""


def _status(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        value = payload.get("status") or payload.get("state")
        if isinstance(value, str):
            return value.strip().lower()
    return None


def build_prompt(
    repository_name: str,
    observation: Dict[str, Any],
    codex_review: Optional[Dict[str, Any]] = None,
    context: Optional[str] = None,
    rejected: Optional[List[Dict[str, Any]]] = None,
) -> str:
    codex_block = ""
    if codex_review:
        codex_block = "\n".join(
            [
                "",
                "Codex has already assessed this. Your job is to decide whether",
                "that assessment is actually correct -- agreeing is a valid",
                "answer, and so is contradicting it. Do not defer to it.",
                "",
                f"Codex verdict: {codex_review.get('verdict')}",
                f"Codex confidence: {codex_review.get('confidence')}",
                "",
                (codex_review.get("body") or "").strip(),
                "",
            ]
        )

    return f"""You are the independent engineering reviewer for {repository_name}.

{UNTRUSTED_PREAMBLE}

Do not modify anything. This is a read-only review.
{rejected_block(rejected)}{codex_block}
{f"Repository context:{chr(10)}{context}{chr(10)}" if context else ""}
{observation_block(observation)}

Assess whether this makes engineering sense for {repository_name} as it is
actually built. Cover hidden implementation risk, whether a simpler
alternative exists, and any security implications.

End your answer with a fenced JSON block, and nothing after it:

{VERDICT_SCHEMA}"""


def call_routine(
    prompt: str,
    *,
    config: Optional[RoutineConfig] = None,
    metadata: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.Client] = None,
) -> str:
    """POST the prompt, poll if the routine returns a job, return the answer."""
    config = config or RoutineConfig.from_env()
    headers = {"Content-Type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(config.timeout_s))

    try:
        response = client.post(
            config.url,
            json={"prompt": prompt, "metadata": metadata or {}},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()

        text = extract_text(payload)
        status = _status(payload)
        if text and (status is None or status in TERMINAL_STATES):
            return text
        if status in FAILED_STATES:
            raise RoutineError(f"routine reported {status}: {json.dumps(payload)[:300]}")

        job_id = payload.get("id") or payload.get("job_id") or payload.get("run_id")
        if not job_id:
            raise RoutineError(
                f"routine returned neither an answer nor a job id: "
                f"{json.dumps(payload)[:300]}"
            )

        deadline = time.monotonic() + config.timeout_s
        poll_url = f"{config.url.rstrip('/')}/{job_id}"
        while time.monotonic() < deadline:
            time.sleep(config.poll_interval_s)
            poll = client.get(poll_url, headers=headers)
            poll.raise_for_status()
            payload = poll.json()
            status = _status(payload)
            if status in FAILED_STATES:
                raise RoutineError(f"routine reported {status}")
            text = extract_text(payload)
            if text and (status is None or status in TERMINAL_STATES):
                return text

        raise RoutineError(f"routine did not finish within {config.timeout_s:.0f}s")
    except httpx.HTTPError as exc:
        raise RoutineError(f"routine request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()


def review_observation(
    repository,
    observation: Dict[str, Any],
    *,
    codex_review: Optional[Dict[str, Any]] = None,
    context: Optional[str] = None,
    rejected: Optional[List[Dict[str, Any]]] = None,
    config: Optional[RoutineConfig] = None,
    caller=None,
):
    """Ask the Claude routine about one observation."""
    from .codex_review import ReviewResult, parse_verdict

    caller = caller or call_routine
    prompt = build_prompt(
        repository.name, observation, codex_review, context, rejected
    )

    try:
        body = caller(
            prompt,
            config=config,
            metadata={
                "repository_id": repository.id,
                "observation_id": observation["id"],
            },
        )
    except RoutineNotConfigured as exc:
        return ReviewResult(
            observation["id"], verdict="error", body="", error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - one bad review is not a failed run
        logger.warning(f"Claude review failed for {repository.id}: {exc!r}")
        return ReviewResult(
            observation["id"],
            verdict="error",
            body="",
            error=f"{type(exc).__name__}: {exc}",
        )

    payload = parse_verdict(body)

    def number(key: str) -> Optional[float]:
        try:
            return max(0.0, min(1.0, float(payload.get(key))))
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


@dataclass(frozen=True)
class RoutineCheck:
    """The result of asking the routine one trivial question."""

    ok: bool
    detail: str
    answer: Optional[str] = None
    verdict: Optional[str] = None

    def describe(self) -> str:
        return ("ok: " if self.ok else "failed: ") + self.detail


PROBE_PROMPT = """This is a connectivity check from ALENA. Do not inspect any
repository and do not do any work.

Reply with exactly one short sentence confirming you received this, then a
fenced JSON block and nothing after it:

```json
{"verdict": "supported", "summary": "connectivity check"}
```"""


def check_routine(config: Optional[RoutineConfig] = None, caller=None) -> RoutineCheck:
    """Ask the routine one trivial question and report what came back.

    This exists because the client has never met a live endpoint. The contract
    it speaks is documented rather than observed, so the first thing anyone
    needs after setting CLAUDE_ROUTINE_URL is to find out whether the envelope
    matches -- and finding that out during a Thursday 02:00 escalation is the
    worst time for it.

    It distinguishes three failures that look the same from the outside: the
    URL is not set, the endpoint could not be reached, and the endpoint
    answered in a shape the client cannot read.
    """
    from .codex_review import parse_verdict

    try:
        config = config or RoutineConfig.from_env()
    except RoutineNotConfigured as exc:
        return RoutineCheck(False, str(exc))

    caller = caller or call_routine
    try:
        answer = caller(
            PROBE_PROMPT, config=config, metadata={"kind": "connectivity-check"}
        )
    except Exception as exc:  # noqa: BLE001
        return RoutineCheck(False, f"{type(exc).__name__}: {exc}")

    if not (answer or "").strip():
        return RoutineCheck(
            False,
            "the routine answered, but the client could not find any text in "
            "the response. Adjust extract_text() in this module to match your "
            "routine's envelope.",
        )

    payload = parse_verdict(answer)
    if payload["verdict"] == "unclear":
        return RoutineCheck(
            True,
            "reachable, and text came back, but no JSON verdict could be "
            "parsed from it. Reviews will still be recorded and readable; "
            "their scores will fall back to neutral.",
            answer=answer,
            verdict=payload["verdict"],
        )

    return RoutineCheck(
        True,
        f"reachable, and a {payload['verdict']!r} verdict parsed cleanly.",
        answer=answer,
        verdict=payload["verdict"],
    )
