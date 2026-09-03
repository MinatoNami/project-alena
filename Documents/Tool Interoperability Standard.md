# Tool Interoperability Standard

## 1. MCP Is the Canonical Tool Protocol

All reusable Alena tools MUST be exposed using the **Model Context Protocol (MCP)**.

Alena should not invent a proprietary tool invocation format as its primary interface.

The objective is:

```text
One Tool Implementation
        │
        ▼
     MCP Server
        │
        ├──► Local LLM Agents
        ├──► Claude Code
        ├──► ChatGPT / OpenAI Agents
        ├──► Codex-compatible workflows
        ├──► IDE Agents
        └──► Future LLM platforms
```

The tool implementation should therefore be independent from the model provider.

---

# 2. Tool Portability Requirement

A tool is considered a valid permanent Alena tool only if it can be exposed through MCP.

This means tools must not depend on:

```text
Claude-specific function formats
OpenAI-specific function formats
LM Studio-specific formats
Alena-specific prompt conventions
```

Instead:

```text
                        MCP
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
       Claude          OpenAI        Local Models
       Code                          / LM Studio
```

Provider-specific adapters may exist, but MCP remains the source-of-truth interface.

---

# 3. MCP Server Architecture

Alena should operate one or more MCP servers.

Recommended structure:

```text
                    PROJECT ALENA
                         │
                    Tool Gateway
                         │
                 MCP Tool Registry
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
 alena-core-mcp    alena-dev-mcp      alena-web-mcp
       │                 │                  │
       ▼                 ▼                  ▼
 Repository          Testing           Research
 Git                 Build             Browser
 Memory              Lint              Releases
 Portfolio           Analysis          Documentation
```

Initially this could also be implemented as one MCP server:

```text
alena-mcp
```

and separated later when security or deployment requirements justify it.

---

# 4. MCP Tool Contract

Every permanent tool MUST define:

- tool name;
- description;
- input schema;
- output schema;
- permission requirements;
- version;
- ownership;
- side-effect classification.

Example:

```json
{
  "name": "dependency.outdated",
  "description": "Find outdated dependencies in a declared repository.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "repository_id": {
        "type": "string"
      }
    },
    "required": [
      "repository_id"
    ]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "dependencies": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string"
            },
            "installed": {
              "type": "string"
            },
            "latest": {
              "type": "string"
            }
          }
        }
      }
    }
  }
}
```

The MCP tool definition is the canonical contract.

---

# 5. Internal Tool Implementation

The MCP interface should be separated from the implementation.

Example:

```text
dependency.outdated
       │
       │ MCP request
       ▼
┌─────────────────────┐
│ MCP Adapter         │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Alena Tool Service  │
└─────────┬───────────┘
          │
          ▼
   package manager
```

This lets the same implementation later be called from:

```text
CLI
REST API
worker job
MCP
unit test
```

without embedding business logic inside the MCP protocol layer.

---

# 6. Local LLM Access

Local models should access tools through an MCP-capable host controlled by Alena.

Architecture:

```text
LM Studio
   │
   ▼
Local Agent Runtime
   │
   │ MCP Client
   ▼
Alena MCP Server
   │
   ▼
Tools
```

The local model itself does not necessarily need native MCP support.

Alena's agent runtime can act as the MCP host.

Therefore:

```text
Local LLM
   │
tool request
   ▼
Agent Runtime
   │
MCP
   ▼
Tool
```

This makes local models interchangeable.

For example:

```text
Qwen
GLM
GPT-OSS
Gemma
future local model
```

can all use the same tool infrastructure.

---

# 7. Claude Access

Claude Code should connect to the same Alena MCP services.

Example:

```text
Claude Code
     │
     │ MCP
     ▼
alena-mcp
     │
     ├── repo.search
     ├── memory.search
     ├── dependency.scan
     ├── architecture.extract
     └── portfolio.search_capability
```

Claude-specific tools should only be created if functionality cannot reasonably be represented through MCP.

Even then, the underlying capability should ideally remain available through MCP.

---

# 8. ChatGPT / OpenAI Access

ChatGPT-compatible Alena tools should also be backed by the same MCP servers.

Architecture:

```text
ChatGPT / OpenAI Agent
          │
          │ MCP
          ▼
      alena-mcp
          │
          ▼
     Alena Tools
```

This allows the research agent to access capabilities such as:

```text
repository.get_profile
repository.get_features
memory.search
research.previous_findings
portfolio.get_projects
recommendation.get_history
```

without building separate OpenAI-specific integrations.

---

# 9. Provider Adapter Layer

Where an AI platform does not expose MCP directly, Alena should use a thin provider adapter.

```text
                         Alena Tool
                             │
                             ▼
                            MCP
                             │
           ┌─────────────────┼──────────────────┐
           │                 │                  │
           ▼                 ▼                  ▼
      Native MCP         OpenAI Adapter      Local Adapter
        Client                 │                  │
           │                   ▼                  ▼
         Claude          Function Calls      Model Runtime
```

The important rule is:

> The adapter translates the MCP contract.

It must not redefine the tool.

---

# 10. No Duplicate Provider Tools

Avoid:

```text
tools/
├── claude/
│   └── dependency_scan.py
│
├── openai/
│   └── dependency_scan.py
│
└── local/
    └── dependency_scan.py
```

Prefer:

```text
tools/
└── dependency_scan/
    ├── implementation.py
    ├── mcp.py
    ├── tool.yaml
    └── tests/
```

One implementation.

One MCP contract.

Many consumers.

---

# 11. Tool Registry and MCP Discovery

The Tool Registry should derive its callable interface from MCP discovery.

Conceptually:

```text
Agent
  │
  ▼
MCP tools/list
  │
  ▼
Available Tools
```

Alena may add additional policy metadata around discovered tools:

```yaml
dependency.outdated:
  mcp_server: alena-dev-mcp

  risk:
    level: read-only

  allowed_agents:
    - repository-analyzer
    - thinking-agent
    - codex
    - claude-code

  repositories:
    - "*"
```

The MCP definition describes HOW to call the tool.

Alena policy describes WHO may call it and WHERE.

---

# 12. Separation of Protocol and Policy

This distinction is critical.

MCP answers:

```text
What tools exist?
What arguments do they accept?
What do they return?
How are they invoked?
```

Alena answers:

```text
Who may use them?
Against which repository?
Under what circumstances?
Does the call need approval?
What credentials may it access?
```

Architecture:

```text
Agent
  │
  ▼
MCP Tool Request
  │
  ▼
ALENA POLICY GATE
  │
  ├── Agent allowed?
  ├── Repository allowed?
  ├── Operation allowed?
  ├── Human approval required?
  └── Credentials allowed?
          │
          ▼
       Tool Call
```

---

# 13. Side-Effect Classification

Every tool MUST declare its impact.

Recommended classifications:

```text
READ_ONLY
LOCAL_WRITE
REPOSITORY_WRITE
REMOTE_WRITE
INFRASTRUCTURE_CHANGE
DESTRUCTIVE
```

Examples:

```text
repo.read_file
→ READ_ONLY

git.create_branch
→ REPOSITORY_WRITE

github.create_pr
→ REMOTE_WRITE

terraform.apply
→ INFRASTRUCTURE_CHANGE

database.drop_table
→ DESTRUCTIVE
```

Alena uses these classifications when deciding whether approval is required.

---

# 14. Agent-Built Tools Must Also Be MCP-Compatible

Any reusable tool created by an agent MUST eventually become an MCP tool.

Lifecycle:

```text
Agent identifies repetitive task
           │
           ▼
     Scratch Script
           │
           ▼
      Tool Candidate
           │
           ▼
   Reusability Evaluation
           │
           ▼
     MCP Tool Contract
           │
           ▼
     Implementation
           │
           ▼
         Tests
           │
           ▼
     Security Review
           │
           ▼
       MCP Server
           │
           ▼
       Tool Registry
```

A generated tool is not considered promoted merely because its code works.

Promotion requires:

```text
valid MCP contract
+
tests
+
documented permissions
+
security classification
+
version
+
approval
```

---

# 15. Generated Tool Example

An agent repeatedly analyzes ROS 2 launch systems.

It proposes:

```text
ros2.inspect_launch_graph
```

Implementation:

```text
alena-tools/
└── generated/
    └── ros2_inspect_launch_graph/
        ├── implementation.py
        ├── server.py
        ├── tool.yaml
        ├── README.md
        └── tests/
```

MCP contract:

```json
{
  "name": "ros2.inspect_launch_graph",
  "description": "Inspect ROS 2 launch files and return nodes, topics and launch relationships.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "repository_id": {
        "type": "string"
      }
    },
    "required": [
      "repository_id"
    ]
  }
}
```

After registration:

```text
Claude Code ──────┐
                  │
ChatGPT ──────────┼──► ros2.inspect_launch_graph
                  │
Local Qwen ───────┤
                  │
Future Agent ─────┘
```

No rewrite is required.

---

# 16. MCP Resource Support

Not everything should be exposed as a tool.

Stable context should use MCP Resources where appropriate.

Examples:

```text
alena://repositories/luma-index/profile

alena://repositories/luma-index/architecture

alena://repositories/luma-index/recommendations

alena://portfolio/capabilities
```

This allows MCP-compatible clients to retrieve structured context without pretending every read operation is an executable action.

---

# 17. Tool vs Resource

Use:

```text
MCP Resource
```

for relatively static/readable information.

Examples:

```text
repository profile
architecture documentation
latest recommendation
capability registry
```

Use:

```text
MCP Tool
```

when an action or computation is required.

Examples:

```text
run tests
perform dependency scan
search code
create branch
create PR
analyze architecture
```

---

# 18. Future-Proofing

Alena should treat MCP as an external interoperability boundary, while keeping internal capability implementations protocol-neutral.

Therefore:

```text
                     INTERNAL SERVICE
                           │
                  ┌────────┼─────────┐
                  ▼        ▼         ▼
                 MCP      CLI       API
                  │
       ┌──────────┼───────────┐
       ▼          ▼           ▼
    Claude     OpenAI      Local LLM
```

If another interoperability standard becomes important later, a new adapter can be implemented without rebuilding the tools themselves.

---

# 19. Mandatory Tool Development Rules

Every permanent Alena tool MUST:

1. Have a deterministic machine-readable schema.
2. Provide an MCP-compatible interface.
3. Declare input and output schemas.
4. Declare required permissions.
5. Declare side effects.
6. Be independently testable.
7. Have semantic versioning.
8. Produce structured errors.
9. Avoid provider-specific assumptions.
10. Be usable without requiring a particular LLM vendor.
11. Be auditable through Alena's Tool Gateway.
12. Be independently disableable.
13. Be sandboxable where practical.
14. Never expand its own permissions.

This applies equally to:

```text
human-written tools
agent-generated tools
third-party tools
```

---

# 20. Core Design Rule

The long-term tool architecture should follow:

```text
BUILD ONCE
    │
    ▼
MCP INTERFACE
    │
    ├── Local LLM
    ├── Claude
    ├── ChatGPT
    ├── Codex
    ├── IDE Agents
    └── Future Models
```

Therefore the system's capabilities belong to **Project Alena**, not to the LLM vendor currently using them.