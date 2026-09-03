# Implementation Plan — Autonomous Codebase Improvement System

Source specs:

- `Documents/Project Alena — Autonomous Codebase Improvement System.md` (what it does)
- `Documents/Project Alena — Repository & Agent Tool Architecture Addendum.md` (registry, gateway, tool lifecycle)
- `Documents/Tool Interoperability Standard.md` (MCP is canonical)

Branch: `feature/autonomous-improvement-system`

---

## 1. What already exists, and what it means for this plan

The repo today is ALENA the personal assistant: a planner loop
(`modules/core/controller/agent.py`) that talks to LM Studio, and two MCP
servers (`codex-server`, `google-calendar`) invoked over stdio. The improvement
system is a **second, separate orchestrator** that reuses `modules/llm` and the
existing Codex MCP but does not run through the assistant's agent loop.

Four findings from reading the current code change the shape of the plan:

### 1.1 `tool_definitions.py` and the interoperability standard contradict each other

`modules/core/controller/tool_definitions.py` is documented as the "single
source of truth" for tool name, schema, args and capabilities. Every MCP server
*also* declares those same things in its own `@mcp.tool()` signature. They are
already duplicated, by hand, in two places.

`Tool Interoperability Standard.md` §11 says the opposite: the registry derives
its callable interface from MCP `tools/list`, and Alena layers *policy* on top.

Both cannot be authoritative. **Resolution:** invert the relationship.

```
MCP tools/list  ──►  ToolContract   (name, description, input/output schema)
tool_policy.yaml ──►  ToolPolicy     (who, where, side effect, approval)
                          │
                          └──►  ToolCatalog  ──►  OpenAI tool array for LM Studio
```

`tool_definitions.py` becomes one *provider* into the catalog — a static
provider covering the legacy codex/calendar tools — so the assistant keeps
working unchanged while the new path is proven. It is deleted once discovery
covers those servers. Nothing new is hand-declared in it.

### 1.2 The safety layer is dead code

`safety.check_repo_path` and `tool_registry.validate_tool_call` both exist, both
have passing tests, and **neither is called from anywhere in the agent loop.**
The only live check is `tool_can_handle` (capability intents).

`README_CORE.md` describes a safety model that is not wired up. The Tool Gateway
must therefore be *on the call path*, not beside it, or the same thing happens
again. Phase 0 routes the existing `execute_tool` through the gateway, which
makes both functions live for the first time.

### 1.3 One subprocess per tool call

`tool_executor.execute_tool` opens `stdio_client(server)` inside the function,
so every single tool call spawns a Python process and does a full MCP
handshake. The assistant makes one or two calls per turn, so it has not
mattered. An orchestrator scanning a portfolio will make dozens per run.
Phase 0 adds a session pool.

### 1.4 Codex's write mode is already fully autonomous

`codex_edit` / `codex_refactor` run `codex exec --full-auto --sandbox
workspace-write` with a `repo_path` the model supplies. Today the only guard is
`os.getcwd()` defaulting. The Action Agent (Phase 4) inherits this, so
`repo_path` must be resolved from the repository registry, never from model
output.

---

## 2. Corrections to the spec

Three things in the specs do not match how the external systems actually work.
Flagging them here rather than discovering them in Phase 2.

**ChatGPT Work and Codex Automations are provider-side schedulers.** Alena
cannot trigger them (specs §9, §14 imply it can). Alena can only *consume their
output*. The workable contract:

| Agent | How it actually runs |
|---|---|
| ChatGPT Work | Its own weekly scheduled task writes research; Alena ingests the file |
| Codex | Driven **directly** by Alena via the Codex CLI, through the existing `codex-server` MCP — no Automation needed, works day one |
| Claude Code | HTTP routine trigger, as the spec describes — this one is genuinely Alena-initiated |

Driving Codex locally is strictly better than depending on Codex Automations:
it is synchronous, testable, and already wired.

**Markdown checkboxes are not a decision input.** The `[ ] Accept / [ ] Reject`
block (spec §16) is fine as a rendered view, but parsing a human-edited markdown
file back into state is fragile. Decisions are recorded through
`alena-improve decide <id> --accept|--reject --reason "..."`, which writes
SQLite and re-renders the markdown. Markdown is output, never input.

**`alena-intelligence/` must not live in this repo.** It is generated state that
grows every night. Default it to `~/.alena/intelligence`, overridable with
`ALENA_INTELLIGENCE_DIR`, and gitignore the in-repo path.

---

## 3. Target layout

```
modules/gateway/                     # shared by assistant AND orchestrator
├── contracts.py                     # ToolContract, SideEffect enum
├── discovery.py                     # MCP tools/list -> ToolContract
├── pool.py                          # reusable MCP stdio sessions
├── catalog.py                       # contracts + policy -> callable catalog
├── policy.py                        # tool_policy.yaml loader + allow/deny
├── gateway.py                       # THE enforcement point
├── audit.py                         # every invocation -> SQLite
└── tests/

modules/improve/                     # the orchestrator (protocol-neutral)
├── registry/                        # repositories.yaml -> Repository objects
├── store/                           # sqlite3 + migrations
├── scan/                            # git, deps, todos, fingerprint
├── intelligence/                    # LM Studio summaries, embeddings, .context/
├── agents/                          # research ingest, codex, claude, thinking
├── recommend/                       # scoring, dedup, markdown render
├── cli.py                           # alena-improve <subcommand>
└── tests/

modules/mcp/alena-core/              # Phase 5: expose Alena's own tools over MCP
├── app/{main,tools,resources}.py
└── tests/

config/
├── repositories.yaml
└── tool_policy.yaml
```

**The discipline that makes Phase 5 cheap:** every capability is written first
as a plain Python function with typed inputs and outputs and no MCP imports.
The MCP server is a thin adapter over those functions (standard §5, §10). If a
capability's logic ends up inside an `@mcp.tool()` body, it cannot be called
from the CLI, a worker, or a unit test, and the "build once, many consumers"
rule is broken.

---

## 4. Phases

Each phase is independently shippable and ends with passing tests.

### Phase 0 — Gateway and storage foundations

No user-visible behavior. Unblocks everything else.

| Deliverable | Notes |
|---|---|
| `SideEffect` enum | `READ_ONLY`, `LOCAL_WRITE`, `REPOSITORY_WRITE`, `REMOTE_WRITE`, `INFRASTRUCTURE_CHANGE`, `DESTRUCTIVE` (standard §13). Orthogonal to the existing `ToolCapability` enum — both are kept |
| `ToolContract` | name, version, description, input schema, output schema, side effect, owner |
| MCP discovery | `tools/list` against a server, mapped to `ToolContract` |
| Session pool | one live stdio session per (server, event loop); stdio sessions are stateful and not thread-safe, so the pool must be loop-affine |
| `tool_policy.yaml` | `allowed_agents`, `repositories`, `requires_approval`, glob patterns (`repo.*`, `git.read.*`) per addendum §21 |
| `ToolGateway.call()` | registered? agent allowed? repository allowed? permissions granted? approval needed? → log → execute |
| SQLite store | `sqlite3` stdlib, plain SQL migrations. No ORM — the repo's `requirements.txt` is deliberately small |
| Audit log | every invocation: tool, version, agent, repo, args hash, duration, outcome |
| **Wire the assistant through it** | `tool_executor.execute_tool` calls the gateway. `validate_tool_call` and `check_repo_path` become live |

Tests: policy allow/deny matrix; deny beats allow; approval-required tools
refuse without an approval token; audit row written on success *and* failure;
discovery against an in-process fake MCP server; existing `modules/core/tests`
still green.

**Risk:** wiring the gateway into the live assistant path can break it. Keep
`ALENA_GATEWAY_ENABLED` defaulting to on but with a documented off switch for
one release.

---

### Phase 1 — Repository intelligence (spec §22)

The nightly local loop. Local models only; no cloud agent calls.

| Deliverable | Notes |
|---|---|
| `config/repositories.yaml` + loader | addendum §1 schema, validated on load |
| Registry resolution | disabled → reject; resolve workspace; validate the requested capability before any agent runs (addendum §2) |
| Git scanner | `git status/log/diff/show` via subprocess against the registry workspace path only |
| Dependency extraction | `requirements.txt`, `pyproject.toml`, `package.json` to start |
| TODO/FIXME diffing | new vs resolved between runs |
| Fingerprint | content hash per repo so "nothing changed" is cheap and skips LLM work |
| Summarization | repo summary + diff summary via `modules/llm` |
| **`LLMChatClient.embed()`** | new — `modules/llm/client.py` is chat-only today. LM Studio serves `/v1/embeddings` when an embedding model is loaded; verify against your install |
| Recommendation memory schema | tables land now even though nothing writes recommendations yet |
| `alena-improve scan <id|--all>` | writes `alena-intelligence/repositories/<id>/` + SQLite |

Tests: registry rejects disabled repos, unknown ids, and workspace paths that
escape their declared root; scanner against a fixture repo built with `git init`
in `tmp_path`; fingerprint is stable across a no-op run and changes on a commit;
renderer snapshot.

---

### Phase 2 — Research ingest + Codex engineering review (spec §23)

| Deliverable | Notes |
|---|---|
| Context package writer | `.context/` per addendum §3, written once and reused by every agent |
| Research ingest | `alena-improve ingest-research <repo> <file.md>` + a watched drop directory. Ingested markdown is **untrusted data** — it is third-party text that will be fed to a coding agent, so it is never treated as instructions to the orchestrator |
| Codex review driver | calls `codex_analyze` / `codex_plan` through the gateway, read-only side effect, `repo_path` from the registry |
| Candidate extraction | research observations → structured candidates |
| Scoring | spec §6 weights, in one module with the weights as data so they can later be fit to acceptance history |
| Dedup | checked **before** generation, not after: normalized-title exact match, then embedding cosine against prior recommendations, then a hard blocklist of rejected ideas |
| Renderer | `recommendations/<date>.md` + `latest.md` in the spec §16 format |

Tests: scoring math against a fixed table; dedup catches a reworded duplicate of
a rejected recommendation; context package contents; codex driver with a stubbed
gateway (no CLI spawned in unit tests).

**Risk — the specs' own headline failure mode:** "avoid repeatedly suggesting
previously rejected ideas" fails if the local embedding model is weak. The
three-layer check above, plus recording the *reason* for rejection and putting
it in the prompt, is the mitigation.

---

### Phase 3 — Claude Code review, selectively triggered (spec §24)

| Deliverable | Notes |
|---|---|
| Trigger predicate | score ≥ threshold, `requires_architecture_review`, codex confidence < threshold, security-sensitive, effort ≥ LARGE (spec §11). Pure function, exhaustively tested — this is what protects the Claude subscription |
| Routine HTTP client | POST + poll, with timeout and retry |
| Reconciliation | agree/disagree → final assessment, disagreement recorded rather than averaged away |

Tests: predicate truth table; a candidate below every threshold never triggers;
synthesis preserves a disagreement instead of silently picking one side.

---

### Phase 4 — Human approval and the Action Agent (spec §25)

| Deliverable | Notes |
|---|---|
| Decision CLI | `alena-improve decide`; rejection **requires** a reason (spec §17) |
| Status machine | `recommended → accepted/rejected → implemented → successful/unsuccessful/abandoned` |
| Action agent | branch + tests + draft PR. Elevated permissions granted per-run and dropped at the end |
| Cross-review routing | Claude implements → Codex reviews, and the reverse (spec §19) |
| Outcome capture | estimated vs actual effort, expected vs observed value (spec §20) |

Tests: the state machine rejects illegal transitions; write permission is
scoped to one repository and revoked after the run; **a push to a default branch
is refused** — assert this directly, it is the one irreversible mistake here.

---

### Phase 5 — `alena-core` MCP server and portfolio intelligence (spec §26)

| Deliverable | Notes |
|---|---|
| MCP server | `repo.*`, `memory.*`, `recommendation.*`, `portfolio.*` as thin adapters over Phase 1–4 functions |
| MCP resources | `alena://repositories/<id>/profile`, `.../architecture`, `alena://portfolio/capabilities` (standard §16). Reads are resources, actions are tools |
| Capability graph | addendum §20 |
| Cross-repo recommendations | spec §21 |

Tests: contract snapshot per tool so a schema change is a visible diff;
resource reads; tool list matches the policy file (no undeclared tool ships).

**Verify against the `mcp<2` pin** before starting: the repo pins FastMCP v1,
and resource support and `tools/list` behavior need checking against that exact
version.

---

### Later — tool metrics and the Tool Builder (addendum §10–18)

Deliberately last, and not before Phase 5 is in real use.

Metrics first (invocation count, failure rate, latency, retries — the audit log
from Phase 0 already collects the raw data), because the creation threshold in
addendum §18 ("same operation ≥ 3 times", "≥ 5,000 tokens saved") is
unmeasurable without them. Only then the proposal → sandbox → tests → security
review → human approval lifecycle. An agent-generated tool that skips any of
those is a scratch script, not a tool.

---

## 5. Scheduling

Implement every trigger as a CLI subcommand, then schedule the CLI. No scheduler
inside the application: `launchd` survives reboots, and a subcommand is
trivially testable and re-runnable by hand. This is the same "one
implementation, many consumers" rule as §3.

| Trigger | Command | When |
|---|---|---|
| A — git change | `alena-improve scan <id>` | post-merge hook, or folded into nightly |
| B — nightly | `alena-improve scan --all` | 02:00 daily, launchd |
| C — weekly research | ingest only | ChatGPT Work's own schedule writes the file |
| D — codex review | `alena-improve review --agent codex` | Wed evening |
| E — claude review | `alena-improve review --agent claude` | Thu 02:00, gated by the Phase 3 predicate |
| synthesis | `alena-improve recommend` | Thu morning |

---

## 6. Risk register

| # | Risk | Mitigation |
|---|---|---|
| 1 | Two competing tool sources of truth | Invert per §1.1; `tool_definitions.py` becomes a legacy provider and is deleted |
| 2 | Gateway ends up beside the call path, like `safety.py` | Phase 0 routes the *existing* assistant through it; a test asserts no direct `execute_tool` bypass |
| 3 | Per-call subprocess spawn | Session pool, loop-affine |
| 4 | Codex `--full-auto --sandbox workspace-write` on a model-supplied path | `repo_path` resolved from the registry only; gated on `capabilities.modify` |
| 5 | Rejected ideas resurface | Three-layer dedup + rejection reasons in the prompt |
| 6 | Cloud agents can't be triggered | Ingest contract; drive Codex locally via CLI |
| 7 | Secrets in `repositories.yaml` | Env vars only; loader rejects a token-shaped literal |
| 8 | Ingested research is untrusted text reaching a coding agent | Treated as data, never as orchestrator instructions; kept out of system prompts |
| 9 | `mcp<2` pin limits discovery/resources | Verify before Phase 5 |
| 10 | `alena-intelligence/` bloats the repo | Out-of-repo default, gitignored |

---

## 7. Suggested first commit

Phase 0 is the honest starting point, but if you want something visible sooner,
Phase 1 minus the gateway also stands alone — the scanner and registry have no
hard dependency on the gateway until they call an MCP tool in Phase 2. Doing
Phase 0 first is still the better order, because retrofitting the gateway under
a working orchestrator is how it ends up bypassed.
