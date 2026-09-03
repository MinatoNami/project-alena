# Project ALENA

**ALENA (Adaptive Learning Enhanced Neural Assistant)** is a locally-run, modular AI assistant designed to act as a privacy-first personal copilot across voice, web, and system workflows.

It combines **on-device LLMs**, **speech-to-text**, and **extensible MCP (Model Context Protocol) servers** to orchestrate tools, automate actions, and provide natural language interaction without relying on cloud-only inference.

---

## ✨ Key Features

- 🧠 **Local LLM Inference**

  - LM Studio over its OpenAI-compatible API
  - Native tool calling, so the planner is not asked to hand-write JSON
  - Runs on this machine or another one on the tailnet

- 🎙️ **Speech-to-Text Interface**

  - Transcription by [text-whisperer](https://github.com/MinatoNami/text-whisperer)
    over the tailnet — no model, GPU or audio stack in this repo
  - WebSocket push-to-talk in the browser; voice memos over Telegram

- 🧩 **MCP-Based Tooling**

  - Modular MCP servers for actions (calendar, reminders, system ops, etc.)
  - Tool auto-registration & discovery
  - Clean separation between reasoning and execution
  - Every call goes through the [Tool Gateway](modules/gateway/README.md):
    policy decides, the audit log records, pooled MCP sessions execute

- 🌐 **Web Interface**

  - Lightweight frontend (Vue / Nuxt-friendly)
  - Single-button record → transcribe → infer MVP flow
  - Designed for rapid iteration

- 🔒 **Privacy-First by Design**

  - Data stays local by default
  - Optional external integrations
  - Ideal for home labs, edge devices, and private deployments

- 🤖 **Telegram Bot Gateway**
  - Bi-directional chat relay to groups
  - Voice memos → text-whisperer → controller response
  - Optional reply in source chat or private DM

---

## 🏗️ High-Level Architecture

```
[ ALENA CLI (alena.py) ]
          │
          ▼
    [ Core Agent Loop ] ───────────────┐
          │                             │
          ▼                             ▼
 [ LM Studio (OpenAI API) ]    [ Tool Executor ]
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
               [ MCP Codex Server ]      [ MCP Google Calendar ]
                        │
                        ▼
                  [ Codex CLI ]
                        │
                        ▼
                 [ Repo / Files ]

[ Web / Mobile UI ] ──WS──> [ Voice Assistant Backend ]
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   [ text-whisperer (tailnet) ]          [ LLM Router ]
      MLX Whisper on Apple GPU             │        │
                                           │        └──> [ LM Studio ]
                                           └──> [ ALENA Controller ] ──> [ Core Agent Loop ]

[ Telegram Bot ] ──voice──> [ text-whisperer (tailnet) ]
      │
      └──text──> [ ALENA Controller (FastAPI) ]
```


---

## 🚀 Use Cases

- Personal AI assistant (voice + chat)
- Local automation hub
- Smart home / IoT orchestration
- Developer productivity assistant
- Robotics & edge-AI control plane
- Telegram group assistant (text + voice)

---

## 🛠️ Tech Stack

- **LLM Runtime:** LM Studio (OpenAI-compatible API)
- **Speech-to-Text:** text-whisperer (MLX Whisper, remote over Tailscale)
- **Frontend:** Vue / Nuxt 4 + Tailwind v4 (@tailwindcss/vite) + @nuxt/ui
- **Backend:** Python / Node.js (modular)
- **Protocols:** MCP, WebSocket, WebRTC
- **Deployment:** Local machine, homelab, edge GPU

## ✅ Requirements

- Python 3.10+
- **LM Studio**, with a model loaded and its server started (default port 1234)
- **[text-whisperer](https://github.com/MinatoNami/text-whisperer)** reachable
  over the tailnet, for voice — running a build that has `POST /api/transcribe`.
  See [Documents/TEXT_WHISPERER_CONTRACT.md](Documents/TEXT_WHISPERER_CONTRACT.md).
- **Codex CLI** (used by the MCP Codex server). If you have access via your plan (e.g., ChatGPT Plus), install the Codex CLI and make sure it’s available in your `$PATH`.

Notes:

- The MCP Codex server uses the Codex CLI instead of calling the OpenAI API directly.
- This enables local tool execution and avoids the need to wire an OpenAI API key for code-generation features.

---

## 🧭 Project Status

- ✅ Local LLM inference (LM Studio, native tool calling)
- ✅ Remote STT via text-whisperer over the tailnet
- ✅ Web voice interface MVP (web app usable; supports voice memos via Telegram)
- ✅ Telegram integration (text + voice memos → controller)
- ✅ Codex MCP server integration (tool executor wired)
- ✅ Tool Gateway (policy, approval, audit log, pooled MCP sessions)
- 🚧 MCP server expansion (more MCPs planned)
- 🚧 Autonomous codebase improvement system — scanning, research ingest and
  two independent engineering reviewers work end to end; the human approval
  gate and the action agent are next. See
  [modules/improve](modules/improve/README.md),
  [the research contract](Documents/RESEARCH_DOCUMENT_CONTRACT.md) and
  [the implementation plan](Documents/ALENA_IMPROVE_IMPLEMENTATION_PLAN.md)
- 🚧 Adaptive learning (currently stateless; KB + LLM-generated MCP servers coming next)

---

## Run (ALENA CLI + MCP Codex server)

From repo root:

```bash
pip install -r requirements.txt
bash scripts/start_alena_with_all_mcps.sh
```

Environment variables:

- `LLM_BASE_URL` (default `http://localhost:1234`)
- `LLM_MODEL` (default: whichever model LM Studio has loaded)
- `LLM_TIMEOUT` (default `120`)

All services read from the repo root `.env` (see `.env.example`).

---

## Run (Controller API + MCP Codex server)

Use this if another service (Voice Assistant or Telegram bot) needs the controller API.

```bash
bash scripts/start_controller_with_mcp.sh
```

Environment variables:

- `ALENA_CONTROLLER_URL` (default `http://localhost:9000`)
- `LLM_BASE_URL` (default `http://localhost:1234`)
- `LLM_MODEL` (default: whichever model LM Studio has loaded)
- `LLM_TIMEOUT` (default `120`)

All services read from the repo root `.env` (see `.env.example`).

---

## Run (Voice Assistant backend)

```bash
bash modules/voice-assistant/backend/scripts/start_server.sh
```

The backend imports `modules/llm` and `modules/stt` from the repo root, so run
it through that script or set `PYTHONPATH` to the repo root yourself.

Key environment variables:

- `LLM_ROUTE` (`alena` for tool-capable answers, `lmstudio` for raw model output)
- `ALENA_CONTROLLER_URL` (used when `LLM_ROUTE=alena`)
- `LLM_BASE_URL` (used when `LLM_ROUTE=lmstudio`, and for the web UI proxy)
- `TEXT_WHISPERER_URL` / `TEXT_WHISPERER_TOKEN` (transcription)

`GET /health` reports whether text-whisperer is actually reachable, which is
the first thing to check when voice goes quiet.

---

## Run (Voice Assistant frontend)

From `modules/voice-assistant/frontend`:

```bash
npm install
npm run dev
```

- Styling: Tailwind v4 via `@tailwindcss/vite`, global entry at `app/assets/css/main.css`.
- UI kit: `@nuxt/ui` is enabled in `nuxt.config.ts`.

## Run (Telegram Bot → Controller)

From repo root:

```bash
bash scripts/start_telegram_with_controller_mcp.sh
```

Configure in the repo root `.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_TARGET_CHAT_ID`
- `TELEGRAM_CONTROLLER_ENABLED=true`
- `TELEGRAM_CONTROLLER_URL=http://localhost:9000`

Optional:

- `TELEGRAM_SOURCE_CHAT_IDS` (restrict listening)
- `TELEGRAM_ECHO_IN_TARGET` (allow echo in target)
- `TELEGRAM_REPLY_IN_SOURCE` (reply in source chat)
- `TEXT_WHISPERER_URL` (transcription for voice memos)
- `TEXT_WHISPERER_TOKEN` (its `WEB_PASSWORD`)
- `TEXT_WHISPERER_SSL_VERIFY` (set `false` for self-signed certs)

---

## 🧪 Testing

From repo root:

```bash
pytest -v
```

---

## 📌 Philosophy

ALENA is designed as a **control plane for intelligence** — not just a chatbot.

It reasons locally, acts through tools, and scales through modular capabilities while keeping user data sovereign.

---

## 🙌 Acknowledgements

Inspired by modern AI agents, MCP architecture, and the idea of a locally sovereign personal assistant.
