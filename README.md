# Project ALENA

[![tests](https://github.com/MinatoNami/project-alena/actions/workflows/tests.yml/badge.svg)](https://github.com/MinatoNami/project-alena/actions/workflows/tests.yml)

**ALENA (Adaptive Learning Enhanced Neural Assistant)** is a locally-run,
modular AI assistant: a privacy-first personal copilot across voice, web and
system workflows.

It runs inference on a local LLM, acts through MCP tool servers, and reaches
those tools through a policy gateway that decides, records and executes every
call. Nothing leaves the machine unless you configure something that does.

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Tools](#tools)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Running each service](#running-each-service)
- [Configuration](#configuration)
- [Testing](#testing)
- [Documentation](#documentation)
- [Project status](#project-status)

---

## What it does

- **Local LLM inference.** LM Studio over its OpenAI-compatible API, using
  native tool calling — the planner is never asked to hand-write JSON. Runs on
  this machine or another one on the tailnet.
- **Speech to text.** Transcription by
  [text-whisperer](https://github.com/MinatoNami/text-whisperer) over the
  tailnet. No model, GPU or audio stack lives in this repo.
- **MCP tooling.** Three MCP servers, discovered at startup rather than
  hand-listed. Every call from an ALENA agent goes through the
  [Tool Gateway](modules/gateway/README.md): the policy decides, the audit log
  records, a pooled session executes.
- **Web and voice interfaces.** A Nuxt frontend with WebSocket push-to-talk,
  and a Telegram bot that accepts text and voice memos.
- **Autonomous codebase improvement.** Scans declared repositories, ingests
  research, runs two independent engineering reviewers, and — only behind a
  recorded human decision — writes a branch. See
  [modules/improve](modules/improve/README.md).

---

## Architecture

```
  CLI  ·  Web UI  ·  Telegram
                │
                ▼
      ┌───────────────────┐        asks for a plan
      │  ALENA Controller │ ─────────────────────────►  LM Studio
      │  (core agent loop)│ ◄─────────────────────────  (local model)
      └─────────┬─────────┘        prose, or a tool call
                │
                │  every tool call
                ▼
      ┌───────────────────┐
      │    Tool Gateway   │   catalog · policy · approval · audit · pool
      └─────────┬─────────┘
                │
      ┌─────────┼─────────────────┐
      ▼         ▼                 ▼
 codex-server   google-calendar   alena-core
 (Codex CLI)    (Calendar API)    repo · memory · portfolio · resources

  Voice:  browser / Telegram  ──►  text-whisperer (tailnet)  ──►  controller
```

The planner never invokes a tool. It asks the gateway, which answers a fixed
set of questions — is the tool in the catalog, are the arguments complete, is
this agent allowed, is this repository allowed, does a human have to agree —
logs the attempt, and only then calls it.

---

## Repository layout

| Path | What it is |
|---|---|
| [`alena.py`](alena.py) | The CLI entry point: one turn per line of input |
| [`modules/core`](modules/core/README_CORE.md) | The agent loop, planner client, conversation memory, and the FastAPI controller |
| [`modules/gateway`](modules/gateway/README.md) | Tool catalog, policy, approvals, audit log, pooled MCP sessions |
| [`modules/improve`](modules/improve/README.md) | The autonomous improvement orchestrator: scan, research, review, decide, act |
| [`modules/mcp/alena-core`](modules/mcp/alena-core/README.md) | ALENA's own capabilities over MCP, read-only, for Claude / ChatGPT / local models |
| [`modules/mcp/codex-server`](modules/mcp/codex-server/README.md) | Code generation, analysis and editing via the Codex CLI |
| [`modules/mcp/google-calendar`](modules/mcp/google-calendar/README.md) | Google Calendar read and write |
| [`modules/llm`](modules/llm) | The blocking chat client for LM Studio, plus embeddings |
| [`modules/stt`](modules/stt) | text-whisperer client |
| [`modules/store`](modules/store) | SQLite connection and migrations (`~/.alena/alena.db`) |
| [`modules/telegram`](modules/telegram/README.md) | Telegram bot gateway |
| [`modules/voice-assistant`](modules/voice-assistant/backend/README.md) | Voice backend (FastAPI + WebSocket) and Nuxt frontend |
| [`config/`](config) | `tool_policy.yaml` and `repositories.yaml` — who may call what, against which repo |
| [`deploy/launchd`](deploy/launchd/README.md) | Scheduled scan, review, recommend and dashboard jobs |
| [`scripts/`](scripts/README.md) | Start scripts for each service combination |
| [`Documents/`](Documents) | Design documents and contracts |

---

## Tools

Twenty-two tools across three MCP servers, plus five readable resources. Every
one is declared in [`config/tool_policy.yaml`](config/tool_policy.yaml) with a
side effect and the agents allowed to call it; **a tool that is not declared
cannot be called, even if a server advertises it.**

| Server | Tools |
|---|---|
| codex-server | `codex_generate` `codex_plan` `codex_analyze` `codex_summarize` `codex_doc_outline` `codex_test_plan` (read-only) · `codex_edit` `codex_refactor` (repository write) |
| google-calendar | `google_list_events` (read) · `google_create_event` `google_update_event` (remote write) · `google_delete_event` (destructive) |
| alena-core | `repo.search` `repo.find_todos` `repo.get_dependencies` `repo.get_history` `memory.search` `recommendation.search` `portfolio.search_capability` `portfolio.dependency_divergence` `resource.list` `resource.read` — all read-only |

alena-core also exposes `alena://repositories`, `alena://repositories/{id}/profile`,
`.../architecture`, `.../recommendations` and `alena://portfolio/capabilities`
as MCP resources. `resource.list` and `resource.read` are the doorway for
clients that cannot read resources — which includes any local model, whose only
channel is the tools array.

The planner is offered exactly the tools its agent identity may call, built
from the same catalog and the same policy that will later judge the call.

---

## Requirements

- **Python 3.12 or 3.14** (CI tests both; the code targets 3.10+ but that floor
  is not exercised)
- **[LM Studio](https://lmstudio.ai)** with a model loaded and its server
  started, port 1234 by default
- **[Codex CLI](https://github.com/openai/codex)** on `$PATH`, for the Codex MCP
  server. Tested against codex-cli 0.153; older releases took a `--full-auto`
  flag that 0.153 removed, and the runner passes `--sandbox` instead
- **[text-whisperer](https://github.com/MinatoNami/text-whisperer)** reachable
  over the tailnet, for voice — see
  [the contract](Documents/TEXT_WHISPERER_CONTRACT.md)

Only the first is needed to start. The rest degrade to the features that use
them.

---

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in what you need
bash scripts/start_alena_with_all_mcps.sh
```

All services read the repo-root `.env`.

---

## Running each service

| Command | What it starts |
|---|---|
| `bash scripts/start_alena_with_all_mcps.sh` | The CLI, with every MCP server |
| `bash scripts/start_controller_with_mcp.sh` | The controller API on `:9000`, for the voice backend and Telegram bot |
| `bash modules/voice-assistant/backend/scripts/start_server.sh` | Voice backend (WebSocket push-to-talk) |
| `npm install && npm run dev` in `modules/voice-assistant/frontend` | Nuxt 4 frontend (Tailwind v4, `@nuxt/ui`) |
| `bash scripts/start_telegram_with_controller_mcp.sh` | Telegram bot wired to the controller |
| `bash scripts/start_alena_core_mcp.sh` | alena-core over stdio, for an external MCP client |
| `bash scripts/start_alena_dashboard.sh` | The improvement dashboard |
| `bash scripts/alena_improve.sh <command>` | The improvement CLI — `scan`, `review`, `recommend`, `pending`, `decide`, `implement`, `portfolio`, `tools`, `status`, and more |

The voice backend imports `modules/llm` and `modules/stt` from the repo root,
so run it through its script or set `PYTHONPATH` to the repo root yourself.
`GET /health` on that backend reports whether text-whisperer is actually
reachable, which is the first thing to check when voice goes quiet.

First-time Google Calendar setup needs one interactive authorisation:

```bash
python modules/mcp/google-calendar/scripts/check_credentials.py
```

Nothing else opens a consent screen — the MCP server is started by tool
discovery on every ALENA process, including background jobs, so it never
prompts.

---

## Configuration

Everything is read from the repo-root `.env`; see
[`.env.example`](.env.example) for the full list.

**Inference**

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:1234` | LM Studio |
| `LLM_MODEL` | *(whatever is loaded)* | Pin a model, or leave blank |
| `LLM_TIMEOUT` | `120` | Seconds |
| `LLM_DEBUG` | `0` | Log raw model replies |
| `ALENA_MAX_TOOL_STEPS` | `3` | Tool calls per turn; the last step is spent on an answer |

**Gateway**

| Variable | Default | Meaning |
|---|---|---|
| `ALENA_TOOL_POLICY` | `config/tool_policy.yaml` | Who may call what |
| `ALENA_DB_PATH` | `~/.alena/alena.db` | Audit log and state, outside the repo on purpose |
| `ALENA_ALLOWED_REPO_ROOTS` | *(empty)* | Roots a path argument must stay inside |
| `ALENA_AUDIT_ARGUMENTS` | `0` | Also store redacted arguments |
| `ALENA_GATEWAY_ENABLED` | `1` | `0` bypasses every policy check. Escape hatch only |

**Services** — `ALENA_CONTROLLER_URL`, `LLM_ROUTE` (`alena` for tool-capable
answers, `lmstudio` for raw model output), `TEXT_WHISPERER_URL` /
`TEXT_WHISPERER_TOKEN`, `TELEGRAM_BOT_TOKEN` / `TELEGRAM_TARGET_CHAT_ID` /
`TELEGRAM_CONTROLLER_ENABLED`, `CALENDAR_TIMEZONE`.

Repositories the improvement system may look at are declared in
[`config/repositories.yaml`](config/repositories.yaml). Capability
defaults are asymmetric on purpose: research and analysis default on, anything
that writes defaults off, and `merge` cannot become true by omission.

---

## Testing

```bash
pytest -q
```

881 tests, and they run with no `.env`, no `~/.alena`, no LM Studio and no
Codex CLI — anything needing state builds it under `tmp_path`, and the tests
that need a live model sit behind `RUN_INTEGRATION_TESTS=1`. CI runs the same
command on push and pull request against Python 3.12 and 3.14.

Some of these tests are enforcement rather than description: a tool cannot ship
without a policy entry, alena-core cannot gain a tool that writes, and the
executor cannot detach from the gateway. Those are meant to fail the build.

---

## Documentation

| Document | What it covers |
|---|---|
| [Tool Interoperability Standard](<Documents/Tool Interoperability Standard.md>) | Why MCP owns the contract and the policy file owns permission |
| [Repository & Agent Tool Architecture Addendum](<Documents/Project Alena — Repository & Agent Tool Architecture Addendum.md>) | The registry, grants, and what the gateway must answer |
| [Autonomous Codebase Improvement System](<Documents/Project Alena — Autonomous Codebase Improvement System.md>) | The design behind `modules/improve` |
| [Implementation plan](Documents/ALENA_IMPROVE_IMPLEMENTATION_PLAN.md) | Phases and what is done |
| [Research document contract](Documents/RESEARCH_DOCUMENT_CONTRACT.md) | What a research file must contain to be ingested |
| [text-whisperer contract](Documents/TEXT_WHISPERER_CONTRACT.md) | The transcription API ALENA expects |

---

## Project status

- ✅ Local LLM inference with native tool calling
- ✅ Remote STT over the tailnet; web voice MVP; Telegram text and voice
- ✅ Tool Gateway — policy, approvals, audit log, pooled sessions
- ✅ MCP discovery across all three servers; the planner is fed from the catalog
- ✅ Autonomous improvement: scanning, research ingest, two reviewers, a human
  approval gate, an action agent that writes a branch — nothing is pushed —
  portfolio intelligence, launchd schedules and a Nuxt review dashboard
- 🚧 More MCP servers
- 🚧 Adaptive learning: currently stateless, with a knowledge base and
  LLM-generated MCP servers next

---

## Philosophy

ALENA is a control plane for intelligence, not a chatbot. It reasons locally,
acts through tools, and grows by adding capabilities — while the data stays
where it started.
