# alena-core MCP server

ALENA's own capabilities, exposed over MCP so that Claude, ChatGPT, a local
model and ALENA's own CLI all reach one implementation instead of three.

```
                    modules/improve/query.py
                              │
                        app/server.py
                              │
                          alena-core
                              │
        ┌─────────────┬───────┴────────┬──────────────┐
        ▼             ▼                ▼              ▼
   Claude Code     ChatGPT        Local model     Future agent
```

## Running it

```bash
scripts/start_alena_core_mcp.sh
```

Point a client at that command. It speaks stdio, like the other servers here.

## Tools and resources

The split follows the interoperability standard: stable readable context is a
**resource**, anything that searches or computes is a **tool**. Pretending a
read is an executable action makes every client treat it as one.

| Resource | What it holds |
|---|---|
| `alena://repositories` | Every repository ALENA may look at |
| `alena://repositories/{id}/profile` | Latest scan: languages, dependencies, TODOs, summary |
| `alena://repositories/{id}/architecture` | The local model's description of how it is built |
| `alena://repositories/{id}/recommendations` | Everything proposed, whatever was decided |
| `alena://portfolio/capabilities` | Shared technology, divergent pins, findings |

| Tool | What it does |
|---|---|
| `repo.search` | Regex over a repository's tracked files |
| `repo.find_todos` | TODO and FIXME markers from the last scan |
| `repo.get_dependencies` | Everything declared, across every manifest |
| `repo.get_history` | Recent scans, newest first |
| `memory.search` | What has been proposed before, and what was rejected |
| `recommendation.search` | Recommendations by text, repository and status |
| `portfolio.search_capability` | Which repositories already use a technology |
| `portfolio.dependency_divergence` | The same dependency pinned differently |
| `resource.list` | The resources above, with their URIs |
| `resource.read` | One resource, by URI |

`memory.search` is the one worth reaching for first. Asking it before
proposing something is how an agent finds out the idea was already turned
down, and why.

## The doorway

The resource/tool split is right, and it is also why ALENA's own planner could
not read any of the resources. A local model reached through LM Studio's
OpenAI-compatible API has exactly one channel — the tools array — and no notion
of a resource at all. Claude and ChatGPT could read a repository's
architecture; the assistant whose architecture it is could not.

`resource.list` and `resource.read` are the doorway. One pair of tools that
says "read a resource", rather than one tool per resource: the resources stay
resources, a client that understands them still reads them directly, and
nothing above is duplicated. Both delegate to the server's own registry, so a
resource added to this file appears through the doorway without anyone
remembering to register it twice.

## Read-only by construction

A client configured to reach this server talks to it **directly**. ALENA's Tool
Gateway is not in that path and cannot be — the gateway governs ALENA's own
agents, not whoever else holds the server's address.

So the safety property is structural rather than enforced at call time: every
tool here reads, none writes — the doorway included, which can only reach
resources, and every resource is a read. `config/tool_policy.yaml` declares all
ten as `read_only`, and `tests/test_server.py` asserts it. Adding a tool that
writes fails the build, which is the point — that decision should be a
conversation, not a commit.

Anything that changes a repository lives behind the approval gate in
`modules/improve/`, reached through the CLI, where a human decision and a
scoped grant stand in front of it.

## Thin by design

`app/server.py` contains no logic. Every body calls a function in
`modules/improve/query.py` and shapes the result. If one grows past that, the
logic belongs in the query layer — where the CLI, a worker and a unit test can
all reach it, which is the "build once, many consumers" rule the standard is
built around.

The repo root is put on `sys.path` in `app/__init__.py`, because a server is
launched from its own directory and this one is an adapter over `modules.*`.
Note that every MCP server in this repo has a package called `app`; the tests
load this one by path under a unique name rather than by directory, or the
first one imported would shadow the rest for the whole test session.

## Tests

```bash
pytest modules/mcp/alena-core
```

They pin the contract — tool names, required arguments, resource URIs — because
that is what every client depends on. A change should show up as a failing test
rather than as a client that quietly stops working.
