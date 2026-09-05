"""The local model investigating a repository, rather than waiting for a document.

The safety property under test is not the prompt. It is that the agent runs as
`research-agent`, which the policy grants nothing but read-only tools, and that
what it produces enters the pipeline as an untrusted observation rather than as
a decision.
"""

import json

import pytest

from modules.improve.agents.local_research import (
    LOCAL_SOURCE,
    RESEARCH_AGENT,
    Candidate,
    investigate,
    parse_candidates,
)


class FakeClient:
    """A model that says whatever the script says, in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.tools_seen = []
        self.calls = 0

    def chat(self, messages, *, system_prompt=None, tools=None):
        self.calls += 1
        self.tools_seen.append([t["function"]["name"] for t in (tools or [])])
        return self.replies.pop(0) if self.replies else "{}"


class FakeGateway:
    """Stands in for the real one, recording who asked for what."""

    def __init__(self, tools=("repo.search", "memory.search"), fail=False):
        self.catalog = self
        self._tools = tools
        self.calls = []
        self.fail = fail

    def openai_tools(self, agent):
        self.agent_asked = agent
        return [{"type": "function", "function": {"name": t}} for t in self._tools]

    def canonical(self, name):
        for known in self._tools:
            if known.replace(".", "_") == name.replace(".", "_"):
                return known
        return name

    async def call(self, server, tool, arguments, *, agent=None, repository_id=None):
        self.calls.append((tool, arguments, agent))
        if self.fail:
            raise RuntimeError(f"{agent} may not call {tool}")
        return "the tool said something"


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def candidates(*titles):
    return json.dumps(
        {
            "candidates": [
                {"title": t, "body": "why", "evidence": "a file"} for t in titles
            ]
        }
    )


# -- parsing ---------------------------------------------------------------


def test_candidates_are_read_out_of_a_fenced_block():
    found = parse_candidates(
        'Here is what I found.\n\n```json\n{"candidates": '
        '[{"title": "Pin the deps", "body": "b", "evidence": "e"}]}\n```'
    )

    assert [c.title for c in found] == ["Pin the deps"]
    assert found[0].evidence == "e"


def test_an_untitled_candidate_is_dropped():
    """An untitled observation is one somebody has to open to identify."""
    found = parse_candidates('{"candidates": [{"body": "b"}, {"title": "Real"}]}')

    assert [c.title for c in found] == ["Real"]


def test_an_empty_list_is_a_valid_answer():
    assert parse_candidates('{"candidates": []}') == []


def test_prose_with_no_json_yields_nothing():
    assert parse_candidates("I had a look and everything seems fine.") == []


def test_more_candidates_than_asked_for_are_capped():
    found = parse_candidates(candidates("a", "b", "c", "d"), limit=2)

    assert len(found) == 2


# -- the loop --------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_investigates_then_proposes(registry):
    repository = registry.resolve("sample")
    gateway = FakeGateway()
    client = FakeClient(
        [
            tool_call("memory.search", query_text="rate limiting"),
            tool_call("repo.find_todos", repository_id="sample"),
            candidates("Pin the dependencies"),
        ]
    )

    run = await investigate(
        repository, client=client, gateway=gateway, use_embeddings=False
    )

    assert run.tool_calls == 2
    assert run.proposed == ["Pin the dependencies"]
    assert run.ok


@pytest.mark.asyncio
async def test_every_tool_call_is_made_as_the_research_agent(registry):
    """The identity is the boundary: the policy grants it read-only tools."""
    repository = registry.resolve("sample")
    gateway = FakeGateway()
    client = FakeClient([tool_call("repo.search", repository_id="sample", pattern="x"),
                         candidates("Something")])

    await investigate(repository, client=client, gateway=gateway, use_embeddings=False)

    assert gateway.agent_asked == RESEARCH_AGENT
    assert [agent for _, _, agent in gateway.calls] == [RESEARCH_AGENT]


@pytest.mark.asyncio
async def test_an_underscored_tool_name_reaches_the_tool_that_was_meant(registry):
    """The model writes `repo_search`; the catalog knows that is `repo.search`.
    Letting it be refused costs a turn to learn that dots matter."""
    repository = registry.resolve("sample")
    gateway = FakeGateway()
    client = FakeClient(
        [tool_call("repo_search", repository_id="sample"), candidates("Found it")]
    )

    await investigate(repository, client=client, gateway=gateway, use_embeddings=False)

    assert [tool for tool, _, _ in gateway.calls] == ["repo.search"]


@pytest.mark.asyncio
async def test_a_refused_tool_is_handed_back_rather_than_raised(registry):
    """A refusal is information the model can act on, and the gateway has
    already recorded the attempt."""
    repository = registry.resolve("sample")
    gateway = FakeGateway(fail=True)
    client = FakeClient([tool_call("codex_edit", repo_path="/"), candidates("Anyway")])

    run = await investigate(
        repository, client=client, gateway=gateway, use_embeddings=False
    )

    assert run.ok, "a refusal is not a crash"
    assert run.proposed == ["Anyway"]


@pytest.mark.asyncio
async def test_running_out_of_steps_still_writes_up_what_it_saw(registry):
    """The alternative is throwing away an investigation that had already
    happened, which is the same mistake the tool step limit used to make."""
    repository = registry.resolve("sample")
    gateway = FakeGateway()
    client = FakeClient(
        [
            tool_call("repo.search", repository_id="sample", pattern="x"),
            tool_call("repo.search", repository_id="sample", pattern="y"),
            candidates("Written under pressure"),
        ]
    )

    run = await investigate(
        repository, client=client, gateway=gateway, max_steps=2, use_embeddings=False
    )

    assert run.tool_calls == 2
    assert run.proposed == ["Written under pressure"]
    assert client.tools_seen[-1] == [], "the write-up turn is offered no tools"


@pytest.mark.asyncio
async def test_an_empty_toolbox_is_an_error_rather_than_imagination(registry):
    """With no tools the model would describe what a project like this usually
    contains, which is the one thing research must not be."""
    repository = registry.resolve("sample")
    gateway = FakeGateway(tools=())
    client = FakeClient([candidates("Invented")])

    run = await investigate(repository, client=client, gateway=gateway)

    assert not run.ok
    assert "no tools" in run.errors[0]
    assert client.calls == 0


@pytest.mark.asyncio
async def test_what_it_proposes_is_marked_as_its_own(registry):
    """Not the operator's. `prompting.preamble_for` reads anything that is not
    the operator as untrusted, which is the right framing for a model marking
    its own homework."""
    from modules.improve.persistence import research_documents

    repository = registry.resolve("sample")
    gateway = FakeGateway()
    client = FakeClient([candidates("Its own idea")])

    await investigate(repository, client=client, gateway=gateway, use_embeddings=False)

    sources = {row["source"] for row in research_documents("sample")}
    assert LOCAL_SOURCE in sources


@pytest.mark.asyncio
async def test_a_repository_that_does_not_grant_research_is_refused(registry):
    repository = registry.resolve("sample")
    object.__setattr__(repository.capabilities, "research", False)

    run = await investigate(repository, client=FakeClient([]), gateway=FakeGateway())

    assert not run.ok
