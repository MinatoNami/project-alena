# Project ALENA

**ALENA (Adaptive Learning Enhanced Neural Assistant)** is a locally-run, modular AI assistant designed to act as a privacy-first personal copilot across voice, web, and system workflows.

It combines **on-device LLMs**, **speech-to-text**, and **extensible MCP (Model Context Protocol) servers** to orchestrate tools, automate actions, and provide natural language interaction without relying on cloud-only inference.

---

## ✨ Key Features

- 🧠 **Local LLM Inference**

  - Runs fully on-device (e.g. via Ollama)
  - GPU-accelerated where available
  - No mandatory cloud dependency

- 🎙️ **Speech-to-Text Interface**

  - Whisper-based transcription
  - WebSocket / WebRTC-ready architecture
  - Push-to-talk friendly

- 🧩 **MCP-Based Tooling**

  - Modular MCP servers for actions (calendar, reminders, system ops, etc.)
  - Tool auto-registration & discovery
  - Clean separation between reasoning and execution

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
  - Voice messages → Whisper → controller response
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
 [ Local LLM (Ollama) ]        [ Tool Executor ]
                                      │
                                      ▼
                              [ MCP Codex Server ]
                                      │
                                      ▼
                                 [ Codex CLI ]
                                      │
                                      ▼
                               [ Repo / Files ]

[ Web / Mobile UI ] ──WS──> [ Voice Assistant Backend ]
                               │
                               ▼
                       [ Whisper STT ]
                               │
                               ▼
                        [ LLM Router ]
                          │       │
                          │       └──> [ ALENA Controller (FastAPI) ] ──> [ Core Agent Loop ]
                          └───────────> [ Local LLM (Ollama) ]

[ Telegram Bot ] ───────────────> [ ALENA Controller (FastAPI) ]
      │
      └── voice ──WS──> [ Remote Whisper STT ]
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

- **LLM Runtime:** Ollama (local)
- **Speech-to-Text:** Whisper
- **Frontend:** Vue / Nuxt 4 + Tailwind v4 (@tailwindcss/vite) + @nuxt/ui
- **Backend:** Python / Node.js (modular)
- **Protocols:** MCP, WebSocket, WebRTC
- **Deployment:** Local machine, homelab, edge GPU

## ✅ Requirements

- Python 3.10+
- Ollama (for local LLM runtime)
- **Codex CLI** (used by the MCP Codex server). If you have access via your plan (e.g., ChatGPT Plus), install the Codex CLI and make sure it’s available in your `$PATH`.

Notes:

- The MCP Codex server uses the Codex CLI instead of calling the OpenAI API directly.
- This enables local tool execution and avoids the need to wire an OpenAI API key for code-generation features.

---

## 🧭 Project Status

- ✅ Local LLM inference
- ✅ Whisper STT integration
- ✅ Web voice interface MVP (web app usable; supports voice memos via Telegram)
- ✅ Telegram integration (text + voice memos → controller)
- ✅ Codex MCP server integration (tool executor wired)
- 🚧 MCP server expansion (more MCPs planned)
- 🚧 Adaptive learning (currently stateless; KB + LLM-generated MCP servers coming next)

---

## Run (ALENA CLI + MCP Codex server)

From repo root:

```bash
pip install -r requirements.txt
bash scripts/start_alena_with_mcp.sh
```

Environment variables:

- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `gpt-oss:20b`)
- `OLLAMA_TIMEOUT` (default `120`)

All services read from the repo root `.env` (see `.env.example`).

---

## Run (Controller API + MCP Codex server)

Use this if another service (Voice Assistant or Telegram bot) needs the controller API.

```bash
bash scripts/start_controller_with_mcp.sh
```

Environment variables:

- `ALENA_CONTROLLER_URL` (default `http://localhost:9000`)
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `gpt-oss:20b`)
- `OLLAMA_TIMEOUT` (default `120`)

All services read from the repo root `.env` (see `.env.example`).

---

## Run (Voice Assistant backend)

From `modules/voice-assistant/backend` (PowerShell, with SSL):

```powershell
python -m uvicorn app.main:app `
  --host localhost `
  --port 8000 `
  --ssl-certfile certs/server.pem `
  --ssl-keyfile certs/server-key.pem
```

Key environment variables:

- `LLM_ROUTE` (`ollama` or `alena`)
- `ALENA_CONTROLLER_URL` (used when `LLM_ROUTE=alena`)
- `OLLAMA_BASE_URL` (used when `LLM_ROUTE=ollama`)

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
- `TELEGRAM_STT_WS_URL` (remote Whisper WebSocket)
- `TELEGRAM_STT_SSL_VERIFY` (set `false` for self-signed certs)

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
