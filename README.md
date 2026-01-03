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

---

## 🏗️ High-Level Architecture

```
[ Web / Mobile UI ]
        │
        ▼
[ Audio Stream (WS / WebRTC) ]
        │
        ▼
[ Speech-to-Text (Whisper) ]
        │
        ▼
[ Local LLM (Ollama) ]
        │
        ▼
[ MCP Control Plane ]
   ├─ Calendar MCP
   ├─ Reminder MCP
   ├─ System MCP
   ├─ Web / Data MCP
```

---

## 🚀 Use Cases

- Personal AI assistant (voice + chat)
- Local automation hub
- Smart home / IoT orchestration
- Developer productivity assistant
- Robotics & edge-AI control plane

---

## 🛠️ Tech Stack

- **LLM Runtime:** Ollama (local)
- **Speech-to-Text:** Whisper
- **Frontend:** Vue / Nuxt (planned)
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

## 📌 Philosophy

ALENA is designed as a **control plane for intelligence** — not just a chatbot.

It reasons locally, acts through tools, and scales through modular capabilities while keeping user data sovereign.

---

## 🙌 Acknowledgements

Inspired by modern AI agents, MCP architecture, and the idea of a locally sovereign personal assistant.
