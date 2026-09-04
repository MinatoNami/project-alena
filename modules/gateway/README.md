# Tool Gateway

Agents do not invoke tools. They ask the gateway.

```
Agent
  │  tool request
  ▼
Tool Gateway
  ├── Is the tool in the catalog?
  ├── Are the arguments complete?
  ├── Is the agent allowed?
  ├── Is the repository allowed?
  ├── Does the path stay inside its root?
  ├── Does a human have to agree?
  └── Log the attempt  ──►  audit log
          │
          ▼
    pooled MCP session  ──►  Tool
```

## Protocol and policy are separate

MCP answers *what tools exist, what they accept, how to call them.* The policy
file answers *who may call them, against which repository, and whether a human
has to agree first.* Neither can answer the other's question, so they live in
different places:

| | Source | File |
|---|---|---|
| Contract | MCP `tools/list` | the server that implements the tool |
| Policy | hand-written | `config/tool_policy.yaml` |

`catalog.static_contracts()` is a migration shim that wraps the legacy
`tool_definitions.py` so the assistant keeps working while discovery is proven
against the existing servers. Nothing new goes in it. A discovered contract
always beats a static one, whichever registers first.

## The policy fails closed

A tool that is not declared in `tool_policy.yaml` cannot be called, even if an
MCP server advertises it. Discovery finding a tool is not permission to use it.
That is what makes "every tool declares its side effect" an enforced rule
rather than a convention — `ToolCatalog.undeclared()` lists anything that has
turned up without a policy entry.

## The catalog is also what the planner is offered

The same catalog that decides whether a call is allowed is what builds the
`tools` array sent to LM Studio, filtered by the agent that will make the call:

```
ToolCatalog.openai_tools("assistant")   ──►  llm_client.ask_llm  ──►  LM Studio
ToolCatalog.system_prompt_section(...)  ──►  the planner prompt
```

One source, so a planner is never shown a tool the policy will refuse it, and
never hidden one it may have. The second is the failure that motivated this:
alena-core's tools were discovered, declared and callable, and still invisible
to ALENA's own planner, because the prompt was built from the static list.

Discovery needs a running loop and a subprocess, so `get_gateway()` cannot do
it — it registers the static contracts and stops. `ensure_discovered()` fills
the rest, and the agent loop awaits it before the first `ask_llm` rather than
before the first tool call: by tool-call time it is already too late for the
model to have asked. It costs one subprocess per process, and a server that
will not start leaves the catalog unmarked so the next turn tries again.

## Side effects

Least to most consequential:

```
read_only  local_write  repository_write  remote_write
infrastructure_change  destructive
```

MCP does not carry this, so the policy file declares it. A server's own
`readOnlyHint` / `destructiveHint` annotations are used only as a hint, and
only ever to guess *upward* — a tool's own claim that it is harmless is
exactly the sort of thing a policy boundary exists not to take on faith.

## Approval

An `Approval` is bound to one tool, one repository, and one exact set of
arguments, so approving "edit repo X to do Y" does not also approve "edit repo
X to do Z". Every `requires_approval` in the shipped policy is currently
`false`: Phase 0 introduces the gateway without changing what the assistant is
already allowed to do. The gate turns on in Phase 4, when there is a human flow
to approve through.

## Sessions

One live MCP session per server, owned by a dedicated task. The owner task is
not incidental: anyio cancel scopes belong to the task that entered them, so a
session entered in one task and closed from another raises. Funnelling every
call through the owner keeps enter, use and exit in one place.

Sessions are bound to their event loop. `alena.py` calls `asyncio.run()` per
line of input, so the CLI gets a fresh loop each turn and its sessions are
discarded — correct, just not a saving. The controller and the orchestrator run
one loop and do benefit.

## Audit

Every attempt is recorded, including refusals. Denials are the more useful
half: they are how you find that an agent keeps reaching for a capability it
does not have, which is the signal the tool-proposal lifecycle acts on. They
are also the raw material for the tool-utility metrics in the architecture
addendum.

Arguments are hashed, not stored — they routinely carry file contents and can
carry credentials. `ALENA_AUDIT_ARGUMENTS=1` additionally keeps a
shallow-redacted copy.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ALENA_GATEWAY_ENABLED` | `1` | `0` bypasses every policy check. Escape hatch only |
| `ALENA_TOOL_POLICY` | `config/tool_policy.yaml` | Relative paths resolve against the repo root |
| `ALENA_DB_PATH` | `~/.alena/alena.db` | Audit log. Outside the repo on purpose |
| `ALENA_AUDIT_ARGUMENTS` | `0` | Also store redacted arguments |
| `ALENA_ALLOWED_REPO_ROOTS` | *(empty)* | Roots `repo_path` must stay inside. Empty means unchecked |

## Tests

```bash
pytest modules/gateway -v
```

The pool and discovery tests run a real MCP server subprocess
(`tests/fake_mcp_server.py`) rather than mocking `stdio_client`. The thing
worth proving — that two calls reach the *same* process — only means something
against a real subprocess.
