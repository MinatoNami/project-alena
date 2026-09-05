"""The local model investigating a repository, instead of waiting for a document.

Research used to be something that happened *to* ALENA. ChatGPT Work wrote a
document on its own schedule, somebody dropped it in a directory, and the cycle
ingested it. That source is fine and it stays. But it meant the one model
running on this machine -- with read access to every declared repository
through alena-core -- could not look at a repository and say what it noticed.

The tools were the missing half and they already exist: `repo.search`,
`repo.find_todos`, `repo.get_dependencies`, `repo.get_history`,
`memory.search`, `recommendation.search` and the portfolio pair. What was
missing was a loop that drives them toward something written down.

**The agent identity is the safety property, not the prompt.** This runs as
`research-agent`, and the policy grants that identity nothing but the
read-only alena-core tools. No `codex_edit`, no calendar, no writes of any
kind. A prompt asking a model not to do something is a request; the gateway
refusing it is a boundary, and that is what this relies on.

**It proposes; it does not decide.** Everything it produces enters the pipeline
as an observation with source `alena-local`, so it is reviewed like any other
untrusted text, scored, deduplicated against what has already been proposed and
rejected, and put in front of a person. A model marking its own homework should
be scrutinised more than a document somebody chose to save, not less --
`prompting.preamble_for` gives it the untrusted framing for exactly that
reason.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from modules.core.controller.logger import logger

from ..registry import Repository
from ..research.propose import propose

RESEARCH_AGENT = "research-agent"
LOCAL_SOURCE = "alena-local"

# Enough turns to look at a few things and then write. The cost of a low limit
# is a shallow answer; the cost of a high one is a model that browses forever,
# so this is deliberately closer to "read three things and commit".
DEFAULT_MAX_STEPS = 10
DEFAULT_MAX_CANDIDATES = 5

_FENCE = re.compile(r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"(?P<body>\{[^{}]*\"candidates\".*\})", re.DOTALL)

SYSTEM_PROMPT = """You are ALENA's research agent.

You investigate one repository and write down improvements worth making. You do
not change anything: every tool you have is read-only, and your output is a
proposal that a human decides on later.

How to work:
- Look before you write. Use the tools to find out what is actually in this
  repository rather than describing what a project like it usually contains.
- Call memory.search BEFORE proposing anything. It tells you what has already
  been proposed and what was rejected, and why. Re-raising a rejected idea
  wastes a review and a person's attention.
- Ground each proposal in something you actually saw: a file, a TODO, a
  dependency, a commit. A proposal with no evidence is an opinion.
- Prefer few, specific and checkable over many and vague. Three real findings
  beat ten plausible ones.

When you are done investigating, reply with ONLY a JSON object, no prose:

{"candidates": [
  {"title": "short imperative title",
   "body": "what to change, why it is worth doing, and how you would know it worked",
   "evidence": "what you saw that supports it"}
]}

An empty list is a valid and useful answer. If the repository looks healthy and
nothing stands out, say so with {"candidates": []} rather than inventing work.
"""


@dataclass
class Candidate:
    title: str
    body: str
    evidence: Optional[str] = None


@dataclass
class InvestigationRun:
    repository_id: str
    candidates: List[Candidate] = field(default_factory=list)
    proposed: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    tool_calls: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def describe(self) -> str:
        if self.errors:
            return f"{self.repository_id}: {self.errors[0]}"
        parts = [f"{self.tool_calls} tool call(s)"]
        if self.proposed:
            parts.append(f"{len(self.proposed)} proposed")
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} already outstanding")
        if not self.candidates:
            parts.append("nothing stood out")
        return f"{self.repository_id}: " + ", ".join(parts)


def parse_candidates(text: str, limit: int = DEFAULT_MAX_CANDIDATES) -> List[Candidate]:
    """Pull the candidate list out of the model's final answer.

    Tolerant on the way in and strict on the way out: a fenced block, a bare
    object, the last one wins. A candidate without a title is dropped rather
    than recorded as an untitled observation somebody has to open to identify.
    """
    for pattern in (_FENCE, _BARE):
        for match in reversed(list(pattern.finditer(text or ""))):
            try:
                payload = json.loads(match.group("body"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or "candidates" not in payload:
                continue
            entries = payload.get("candidates")
            if not isinstance(entries, list):
                continue
            found = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or "").strip()
                if not title:
                    continue
                found.append(
                    Candidate(
                        title=title,
                        body=str(entry.get("body") or "").strip(),
                        evidence=(str(entry.get("evidence")).strip() or None)
                        if entry.get("evidence")
                        else None,
                    )
                )
            return found[:limit]
    return []


def _parse_tool_call(reply: str) -> Optional[Dict[str, Any]]:
    """The client renders a native tool call as this JSON; prose is not one."""
    try:
        parsed = json.loads(reply)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict) and parsed.get("tool"):
        return parsed
    return None


def _tool_result_text(result: Any) -> str:
    """Whatever the MCP call returned, as something to put back in the prompt."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = [str(getattr(item, "text", item)) for item in content]
        return "\n".join(parts)
    return str(content)


async def investigate(
    repository: Repository,
    *,
    client=None,
    gateway=None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    note: Optional[str] = None,
    use_embeddings: bool = True,
    conn=None,
) -> InvestigationRun:
    """Investigate one repository and propose what it finds.

    The repository must grant `research`; the registry decides that, not this.
    """
    run = InvestigationRun(repository.id)

    try:
        repository.require("research")
    except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash
        run.errors.append(str(exc))
        return run

    if gateway is None:
        from modules.gateway import ensure_discovered, get_gateway

        gateway = get_gateway()
        # The alena-core tools arrive by discovery, so without this the agent
        # is handed an empty toolbox and writes from imagination.
        await ensure_discovered(gateway)

    if client is None:
        from modules.llm import LLMChatClient, LLMConfig

        client = LLMChatClient(LLMConfig())

    tools = gateway.catalog.openai_tools(RESEARCH_AGENT)
    if not tools:
        run.errors.append(
            f"the policy grants {RESEARCH_AGENT} no tools, so there is nothing "
            "to investigate with"
        )
        return run

    from modules.gateway.catalog import server_parameters

    server = server_parameters("alena-core")

    opening = (
        f"Investigate the repository `{repository.id}` ({repository.name}). "
        f"Its workspace is {repository.workspace}. "
        "Every tool that takes a repository_id takes that id."
    )
    if note:
        opening += f"\n\nThe operator asked you to focus on: {note}"

    messages: List[Dict[str, Any]] = [{"role": "user", "content": opening}]
    reply = ""

    for _ in range(max_steps):
        try:
            reply = client.chat(messages, system_prompt=SYSTEM_PROMPT, tools=tools)
        except Exception as exc:  # noqa: BLE001
            run.errors.append(f"the model was unreachable: {exc}")
            return run

        call = _parse_tool_call(reply)
        if call is None:
            break

        # Local models rewrite `repo.search` as `repo_search`; the catalog
        # knows which one it meant, and the alternative is the model spending a
        # turn discovering that dots matter.
        tool = gateway.catalog.canonical(str(call.get("tool")))
        arguments = call.get("arguments") or {}
        messages.append({"role": "assistant", "content": reply})

        try:
            result = await gateway.call(
                server,
                tool,
                arguments,
                agent=RESEARCH_AGENT,
                repository_id=repository.id,
            )
            observed = _tool_result_text(result)
        except Exception as exc:  # noqa: BLE001 - a refusal is information
            # Handed back rather than raised: "you may not call that" is
            # something the model can act on, and the gateway has already
            # recorded the attempt.
            observed = f"That call was refused: {exc}"
            logger.info(f"research-agent refused {tool}: {exc}")

        run.tool_calls += 1
        messages.append(
            {"role": "user", "content": f"Result of {tool}:\n{observed[:4000]}"}
        )
    else:
        # Out of steps with the model still asking for tools. Give it one turn
        # to write up what it has rather than throwing the investigation away.
        messages.append(
            {
                "role": "user",
                "content": (
                    "No more tool calls are available. Reply now with the JSON "
                    "object of candidates, based on what you have already seen."
                ),
            }
        )
        try:
            reply = client.chat(messages, system_prompt=SYSTEM_PROMPT, tools=[])
        except Exception as exc:  # noqa: BLE001
            run.errors.append(f"the model was unreachable: {exc}")
            return run

    run.candidates = parse_candidates(reply, limit=max_candidates)
    if not run.candidates:
        return run

    for candidate in run.candidates:
        result = propose(
            repository,
            candidate.title,
            candidate.body,
            evidence=candidate.evidence,
            source=LOCAL_SOURCE,
            use_embeddings=use_embeddings,
            conn=conn,
        )
        if not result.ok:
            run.errors.append(f"{candidate.title}: {result.error}")
        elif result.duplicate:
            run.duplicates.append(candidate.title)
        else:
            run.proposed.append(candidate.title)

    return run
