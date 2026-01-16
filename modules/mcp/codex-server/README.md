# MCP Codex App

An **MCP (Model Context Protocol) server** that allows agents to **invoke the Codex CLI directly as a tool**.

This enables structured, auditable, and local-first code generation, refactoring, and explanation workflows without relying on interactive terminals.

Designed to integrate cleanly with agent planners (e.g. ALENA) and other MCP servers such as Git, CI, or filesystem tools.

---

## ✨ Features

- 🚀 Direct invocation of **Codex CLI** via MCP tools
- 🧠 Structured tools (`codex_generate`, `codex_edit`, `codex_summarize`, `codex_doc_outline`, `codex_test_plan`)
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
modules/mcp/codex-server/
├── app/
│   ├── __init__.py
│   ├── main.py         # MCP server entrypoint
│   ├── tools.py        # MCP tool definitions
│   └── codex_runner.py # Codex CLI wrapper
├── tests/              # Unit tests for tool wiring and prompts
├── test_mcp.py          # Sample MCP client script
└── README.md
```

---

## 📦 Requirements

- Python **3.10+**
- Codex CLI installed and available in `$PATH`
- MCP Python SDK

---

## 🔧 Installation

### 1. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify Codex CLI

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

## 🧪 Testing

Unit tests validate prompt construction, tool wiring, and Codex CLI invocation logic without spawning real processes.

From repo root:

```bash
pytest modules/mcp/codex-server/tests -v
```

Manual smoke test using the sample client (requires Codex CLI in PATH):

```bash
python modules/mcp/codex-server/test_mcp.py
```

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

### `codex_plan`

Produce a multi-step plan and file-level strategy for a complex task.

```json
{
  "tool": "codex_plan",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "goal": "Add rate limiting to the public API"
  }
}
```

---

### `codex_analyze`

Analyze a repository question without modifying files.

```json
{
  "tool": "codex_analyze",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "question": "Where is authentication enforced and how is it configured?"
  }
}
```

---

### `codex_summarize`

Summarize the repository or a specific focus area.

```json
{
  "tool": "codex_summarize",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "focus": "architecture and data flow"
  }
}
```

---

### `codex_doc_outline`

Draft a documentation outline for a given topic and audience.

```json
{
  "tool": "codex_doc_outline",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "topic": "Authentication and authorization",
    "audience": "backend engineers"
  }
}
```

---

### `codex_test_plan`

Produce a test plan for validating a feature or change.

```json
{
  "tool": "codex_test_plan",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "goal": "New password reset flow"
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

### `codex_refactor`

Perform a multi-file refactor with optional constraints.

```json
{
  "tool": "codex_refactor",
  "arguments": {
    "repo_path": "/home/user/repos/my-project",
    "goal": "Split the monolithic service into smaller modules",
    "constraints": "Keep public interfaces stable"
  }
}
```

---

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
