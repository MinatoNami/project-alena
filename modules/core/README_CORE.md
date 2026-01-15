# Project ALENA – Core Module

This folder contains the **core agent logic** for Project ALENA.
It is intentionally **framework-agnostic, testable, and infrastructure-light**.

The goal of this module is to define _how the agent thinks and acts_ — not how tools are implemented.

---

## 🧠 Core Responsibilities

The core module is responsible for:

- Agent control flow (reason → decide → act → reflect)
- Tool-call parsing and validation
- Safety enforcement (filesystem / repo guards)
- Output normalization
- Dependency injection for tool execution
- Deterministic, unit-testable behavior

It **does not**:

- Hard-code infrastructure (MCP, Ollama, Codex)
- Perform I/O directly (except via injected executors)
- Contain UI, voice, or transport logic

---

## 📂 Folder Structure

```
modules/core/
├── controller/
│   ├── agent.py            # Main agent loop
│   ├── normalize.py        # Normalize LLM / tool outputs
│   ├── logger.py           # Core logger
│   ├── safety.py           # Repo & path safety checks
│   ├── tool_registry.py    # Tool schema & validation
│   ├── tool_executor.py    # MCP-based tool executor (pluggable)
│   └── ollama_client.py    # Ollama client (lazy import)
│
├── tools/
│   └── tool_capabilities.py # Tool capability model
│
├── tests/
│   ├── test_agent_no_tool.py
│   ├── test_agent_stubbed_ollama.py
│   ├── test_agent_tool_call.py
│   ├── test_normalize_codex_output.py
│   ├── test_safety.py
│   └── test_tool_registry.py
│
└── README.md
```

---

## 🔁 Agent Execution Flow

```
User Input
   ↓
Ollama (LLM)
   ↓
Is JSON tool call?
   ├── No → return final text
   └── Yes
        ↓
   Validate tool schema
        ↓
   Capability checks
        ↓
   Safety checks
        ↓
   Execute tool (via injected executor)
        ↓
   Normalize output
        ↓
   Feed back into agent loop
```

---

## 🔌 Dependency Injection (Critical Design)

The agent does **not** know how tools are executed.

Instead, it accepts a `tool_executor`:

```python
await run_agent(
    "Write hello world",
    tool_executor=my_executor
)
```

### Why this matters

- Unit tests never spawn real processes
- MCP is optional
- Future tools (Git, FS, HTTP) drop in cleanly
- Enables approval gates & dry-runs

---

## 🛡 Safety Model

Safety is enforced **before execution**:

- Allowed repo paths are whitelisted
- Tool schemas are strictly validated
- No filesystem access without explicit approval
- Designed to support future diff-only gates

This prevents the agent from:

- Escaping project boundaries
- Modifying unintended files
- Executing malformed tool calls

---

## 🧰 Tool Capabilities

Tools declare capabilities in `modules/core/tools/tool_capabilities.py` to block unsafe requests.

- `codex_generate`: code generation only
- `codex_edit`: file edits only

If the user explicitly asks to use Codex, the agent will honor that request even when capability
checks would otherwise block it (e.g. asking Codex for the current time).

---

## 🧪 Testing Philosophy

All core logic is covered by **pure unit tests**.

- Ollama is stubbed
- Tool execution is injected
- MCP is never started in unit tests
- Integration tests are explicitly marked & skipped

Run tests from repo root:

```bash
pytest modules/core/tests -v
```

---

## 🚀 Extending the Core

This module is designed to support:

- Diff-only approval gates
- Planner / multi-step reasoning
- Tool chaining
- Memory injection
- Voice & UI layers
- Multi-model routing

All without modifying the core agent loop.

---

## 🧩 Design Principle

> **The core decides _what_ to do.  
> Executors decide _how_ it is done.**

This separation is what makes ALENA safe, testable, and extensible.

---

## 📌 Next Steps

Recommended additions on top of this core:

1. Diff-only approval gate
2. Git MCP (apply / rollback)
3. Planner loop
4. Memory layer
5. Voice interface

---

**This core is production-grade.**
