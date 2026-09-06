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

# Enough turns to search, read what the search found, and then write. Reading
# is what stops it proposing work that is already done, and reading costs a
# turn per file -- so this is higher than it looks like it needs to be. The
# cost of a low limit is a confident guess.
DEFAULT_MAX_STEPS = 14
DEFAULT_MAX_CANDIDATES = 5
# Per tool result. Enough for a file worth reading, bounded so fourteen of them
# do not become the whole context window.
MAX_RESULT_CHARS = 3500
# Research turns are long: fourteen steps of accumulated file contents is a
# much bigger prompt than a chat message, and the local model slows down as it
# grows. The assistant's 120s default is not the right number here, so it is
# raised unless the operator has said what they want.
RESEARCH_TIMEOUT_S = 420.0
# How many tool results stay in the prompt verbatim. Everything a model reads
# accumulates, so a fourteen-step investigation that reads six files carries
# all six into every later turn -- and a local model gets slower as that grows,
# until a turn does not finish at all. Recent results are what it is reasoning
# about; older ones it can read again if it needs them.
KEEP_FULL_RESULTS = 3

_FENCE = re.compile(r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"(?P<body>\{[^{}]*\"candidates\".*\})", re.DOTALL)

SYSTEM_PROMPT = """You are ALENA's research agent.

You investigate one repository and write down improvements worth making. You do
not change anything: every tool you have is read-only, and your output is a
proposal that a human decides on later.

How to work:
- Look before you write. Use the tools to find out what is actually in this
  repository rather than describing what a project like it usually contains.
- memory.search tells you what has already been proposed and what was
  rejected. Search it with *specific words from an idea you are considering*,
  not a general one: "test coverage" finds something, "improvements" finds
  nothing. Every candidate is checked against memory by name before it is
  recorded, and you will be asked to withdraw anything already decided -- so
  re-raising a rejected idea only wastes your own turn.
- **Before saying something is missing, read the code and check.** Finding
  where a thing is *mentioned* is not the same as knowing whether it exists.
  repo.search finds the file; repo.read_file opens it. The most common way to
  waste a reviewer's time is proposing work that is already done.
- Searching a word gets you every place the word appears, including plans,
  comments and string literals. Pass `context` to see what a hit sits in, and
  `exclude` (e.g. "Documents/*") when you want code rather than the documents
  that describe it. A match inside a markdown table is not a code problem.
- Ground each proposal in something you actually read: a file and what it
  does, a dependency, a commit. A proposal with no evidence is an opinion.
- Prefer few, specific and checkable over many and vague. Three real findings
  beat ten plausible ones, and one verified finding beats three guesses.

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
    # The final reply, when it was not the JSON that was asked for. Empty when
    # the model answered properly, including when it properly answered "none".
    unparsed: Optional[str] = None
    # What each candidate resembled, and which the model then withdrew.
    resembled: Dict[str, List[str]] = field(default_factory=dict)
    withdrawn: List[str] = field(default_factory=list)

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
        if self.withdrawn:
            parts.append(f"{len(self.withdrawn)} withdrawn as already decided")
        if self.unparsed:
            parts.append("its final reply was not the JSON asked for")
        elif not self.candidates:
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


def _shrink_old_results(messages: List[Dict[str, Any]]) -> None:
    """Keep the last few tool results in full and collapse the rest.

    Bounding the prompt rather than raising the timeout again: the timeout was
    a symptom. An investigation that reads six files was carrying all six into
    every subsequent turn, and the model slowed down until a turn stopped
    finishing. The header stays so the model can see it looked at something and
    read it again if it matters.
    """
    seen = 0
    for message in reversed(messages):
        content = message.get("content") or ""
        if message.get("role") != "user" or not content.startswith("Result of "):
            continue
        seen += 1
        if seen <= KEEP_FULL_RESULTS or len(content) < 200:
            continue
        header = content.split("\n", 1)[0]
        message["content"] = (
            f"{header}\n[read earlier; dropped from the prompt to keep it small. "
            "Ask again if you need it.]"
        )


def _tool_result_text(result: Any) -> str:
    """Whatever the MCP call returned, as something to put back in the prompt."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = [str(getattr(item, "text", item)) for item in content]
        return "\n".join(parts)
    return str(content)


def memory_notes(repository_id: str, candidates: List[Candidate]) -> Dict[str, List[str]]:
    """What each candidate resembles, and what was already decided about it.

    Searched *per candidate title*, after the candidates exist. The prompt used
    to say "call memory.search before proposing anything", which is the wrong
    moment and the wrong query: an agent that has not yet had an idea searches
    something generic, and a generic query matches nothing. `project-alena`
    and `improvements` both return zero, so the check passed silently and the
    agent went on to re-raise ideas that had been rejected hours earlier.

    A title is a specific query, and it only exists once there is a candidate.
    """
    from ..query import search_memory

    notes: Dict[str, List[str]] = {}
    for candidate in candidates:
        try:
            found = search_memory(candidate.title, repository_id, limit=3)
        except Exception as exc:  # noqa: BLE001 - a failed check is not fatal
            logger.warning(f"memory check failed for {candidate.title!r}: {exc!r}")
            continue
        prior = [
            f"{row.get('status', 'unknown')}: {row.get('title', '')}"
            for row in found.get("recommendations", [])
            if row.get("title") and row.get("title") != candidate.title
        ]
        if prior:
            notes[candidate.title] = prior
    return notes


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
        import os
        from dataclasses import replace

        from modules.llm import LLMChatClient, LLMConfig

        # from_env, not the library defaults: an operator who set LLM_TIMEOUT
        # meant it. Absent that, use a limit that suits a long research turn
        # rather than a chat reply.
        config = LLMConfig.from_env()
        if "LLM_TIMEOUT" not in os.environ:
            config = replace(config, timeout_s=RESEARCH_TIMEOUT_S)
        client = LLMChatClient(config)

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
        # Truncation is announced. A silently cut file read is how a model
        # concludes a function is missing from the half it was shown.
        body = observed[:MAX_RESULT_CHARS]
        if len(observed) > MAX_RESULT_CHARS:
            body += (
                f"\n\n[cut after {MAX_RESULT_CHARS} characters. Read further "
                "with repo.read_file and a higher `start`.]"
            )
        messages.append({"role": "user", "content": f"Result of {tool}:\n{body}"})
        _shrink_old_results(messages)
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

    # The check that actually stops a repeat: ask memory about each candidate
    # by name, then let the model withdraw what it recognises. Only costs a
    # turn when something resembles a prior decision.
    notes = memory_notes(repository.id, run.candidates) if run.candidates else {}
    if notes:
        run.resembled = dict(notes)
        lines = [
            "Before these are recorded, here is what each resembles from this "
            "repository's history, with what was decided:",
            "",
        ]
        for title, prior in notes.items():
            lines.append(f"- {title}")
            lines.extend(f"    already {entry}" for entry in prior)
        lines += [
            "",
            "Reply with the JSON object again, keeping only the candidates that "
            "are genuinely different from what was already decided. Dropping "
            "all of them is a fine answer. Do not reword a rejected idea to "
            "make it look new.",
        ]
        try:
            reply = client.chat(
                [*messages, {"role": "user", "content": "\n".join(lines)}],
                system_prompt=SYSTEM_PROMPT,
                tools=[],
            )
            run.candidates = parse_candidates(reply, limit=max_candidates)
            run.withdrawn = [
                title
                for title in notes
                if title not in {c.title for c in run.candidates}
            ]
        except Exception as exc:  # noqa: BLE001 - keep what we already have
            logger.warning(f"the memory check turn failed: {exc!r}")

    if not run.candidates:
        # "It found nothing" and "I could not read what it said" look identical
        # from the outside and mean opposite things -- one is a healthy
        # repository, the other is a broken agent. Tell them apart.
        if '"candidates"' not in (reply or ""):
            run.unparsed = (reply or "").strip()[:600]
            logger.warning(
                f"{repository.id}: the research agent's final reply was not the "
                f"expected JSON: {run.unparsed[:200]}"
            )
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
