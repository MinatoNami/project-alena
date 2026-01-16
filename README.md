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
[ Web / Mobile UI ]                [ Telegram ]
  │                               │
  ▼                               ▼
[ Audio Stream (WS / WebRTC) ]   [ Telegram Bot ]
  │                               │
  ▼                               ▼
[ Speech-to-Text (Whisper) ]      [ Controller (FastAPI) ]
  │                               │
  ▼                               ▼
[ Local LLM (Ollama) ]             [ MCP Control Plane ]
  │                               ├─ Codex MCP
  ▼                               └─ Other MCP tools
[ MCP Control Plane ]
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

---

## 🧭 Project Status

- ✅ Local LLM inference
- ✅ Whisper STT integration
- 🚧 MCP server expansion
- 🚧 Web voice interface MVP
- 🚧 Adaptive learning layer

---

## Run (ALENA CLI + MCP Codex server)

From repo root:

```bash
pip install -r requirements.txt
bash scripts/start_alena_with_mcp.sh
```

Environment variables:

- `OLLAMA_HOST` (default `http://10.8.0.1:11434`)
- `OLLAMA_MODEL` (default `gpt-oss:20b`)

---

## Run (Voice Assistant backend)

From `modules/voice-assistant/backend` (PowerShell, with SSL):

```powershell
python -m uvicorn app.main:app `
  --host 0.0.0.0 `
  --port 8000 `
  --ssl-certfile certs/10.8.0.1+1.pem `
  --ssl-keyfile certs/10.8.0.1+1-key.pem
```

---

## Run (Voice Assistant frontend)

-

## Run (Telegram Bot → Controller)

From repo root:

```bash
bash scripts/start_telegram_with_controller_mcp.sh
```

Configure in `modules/telegram/.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_TARGET_CHAT_ID`
- `TELEGRAM_CONTROLLER_ENABLED=true`
- `TELEGRAM_CONTROLLER_URL=http://localhost:9000`

Optional:

- `TELEGRAM_SOURCE_CHAT_IDS` (restrict listening)
- `TELEGRAM_ECHO_IN_TARGET` (allow echo in target)
- `TELEGRAM_REPLY_IN_SOURCE` (reply in source chat)

From `modules/voice-assistant/frontend`:

```bash
npm install
npm run dev
```

- Styling: Tailwind v4 via `@tailwindcss/vite`, global entry at `app/assets/css/main.css`.
- UI kit: `@nuxt/ui` is enabled in `nuxt.config.ts`.

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
