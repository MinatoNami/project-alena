# MCP Codex App

An **MCP (Model Context Protocol) server** that allows agents to **invoke the Codex CLI directly as a tool**.

This enables structured, auditable, and local-first code generation, refactoring, and explanation workflows without relying on interactive terminals.

Designed to integrate cleanly with agent planners (e.g. ALENA) and other MCP servers such as Git, CI, or filesystem tools.

---

## ✨ Features

- 🚀 Direct invocation of **Codex CLI** via MCP tools
- 🧠 Structured tools (`codex_generate`, `codex_edit`, `codex_explain`)
- 🔒 No shell execution (safe subprocess calls)
- 📂 Repository-scoped execution
- 📦 Minimal dependencies
- 🧩 Agent- and planner-friendly

---

## 🏗 Architecture

```
[MCP Client / Agent]
        |
        |  MCP tool call (JSON-RPC)
        v
[MCP Codex Server]
        |
        |  subprocess (stdin/stdout)
        v
[Codex CLI]
        |
        v
[Local Filesystem / Git Repo]
```

---

## 📁 Project Structure

```
mcp-codex-app/
├── app/
│   ├── __init__.py
│   ├── main.py        # MCP server entrypoint
│   ├── tools.py       # MCP tool definitions
│   └── codex.py       # Codex CLI wrapper
├── requirements.txt
└── README.md
```

---

## 📦 Requirements

- Python **3.10+**
- Codex CLI installed and available in `$PATH`
- MCP Python SDK

---

## 🔧 Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-org/mcp-codex-app.git
cd mcp-codex-app
```

### 2. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Verify Codex CLI
```bash
codex --help
```

---

## ▶️ Running the MCP Server

```bash
python -m app.main
```

The server will start and expose MCP tools over STDIO.

---

## 🧰 Available MCP Tools

### `codex_generate`
Generate new code or content.

```json
{
  "tool": "codex_generate",
  "arguments": {
    "prompt": "Write a Python function that validates JWT tokens"
  }
}
```

---

### `codex_edit`
Modify an existing repository.

```json
{
  "tool": "codex_edit",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "instruction": "Refactor the logging system to use structured JSON logs"
  }
}
```

---

### `codex_explain`
Explain a file or repository.

```json
{
  "tool": "codex_explain",
  "arguments": {
    "path": "/home/user/repos/my-project"
  }
}
```

---

## 🔐 Security Considerations

- Use repository allow-lists
- Disable `--apply` by default in production
- Enforce execution timeouts
- Log prompts and outputs
- Consider container sandboxing

---

## 🚀 Future Extensions

- Streaming Codex output
- Diff-only preview mode
- Git auto-commit hooks
- Docker sandbox execution
- Planner-based workflows (ALENA)

---

## 📜 License

MIT License
