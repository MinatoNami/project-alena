# Project Alena — Repository & Agent Tool Architecture Addendum

## 1. Repository Registry

Alena maintains an explicit declaration of repositories that are eligible for research, analysis, planning, and improvement.

Example:

```yaml
repositories:
  - id: luma-index
    name: LumaIndex

    source:
      provider: github
      url: https://github.com/example/luma-index.git
      default_branch: main

    workspace:
      path: /srv/alena/repos/luma-index

    enabled: true

    capabilities:
      research: true
      analyze: true
      plan: true
      modify: true
      create_branch: true
      create_pr: true
      merge: false

    agents:
      research:
        - chatgpt-work

      engineering:
        - codex
        - claude-code

      implementation:
        - claude-code
        - codex

    schedule:
      repository_scan: nightly
      research: weekly
      architecture_review: weekly

    tags:
      - web
      - django
      - documents
      - ai

  - id: athena
    name: Project Athena

    source:
      provider: github
      url: https://github.com/example/project-athena.git
      default_branch: main

    workspace:
      path: /srv/alena/repos/athena

    enabled: true

    capabilities:
      research: true
      analyze: true
      plan: true
      modify: true
      create_branch: true
      create_pr: true
      merge: false

    tags:
      - security
      - vulnerability-management
      - agents
```

The registry becomes the authoritative source for:

- where the repository exists;
- which branch is authoritative;
- which agents may inspect it;
- whether agents may modify it;
- whether branches may be created;
- whether pull requests may be opened;
- whether autonomous merging is permitted;
- what schedules apply;
- what technologies/domains the project belongs to.

---

# 2. Repository Selection

Every Alena run begins by resolving a declared target.

Example:

```bash
alena improve luma-index
```

or:

```bash
alena research athena
```

or:

```bash
alena improve --all
```

Internally:

```text
Requested Target
      │
      ▼
Repository Registry
      │
      ├── disabled → reject
      │
      └── enabled
              │
              ▼
       Resolve workspace
              │
              ▼
       Validate permissions
              │
              ▼
          Agent Run
```

Agents should never be given arbitrary filesystem access.

Instead they receive something such as:

```json
{
  "repository_id": "luma-index",
  "workspace": "/srv/alena/repos/luma-index",
  "permissions": {
    "read": true,
    "write": false,
    "git_branch": false
  }
}
```

The orchestrator controls access.

---

# 3. Repository Context Package

Before sending work to any external agent, Alena generates a context package.

Example:

```text
.context/
├── repository.yaml
├── architecture.md
├── dependencies.json
├── recent_changes.md
├── previous_recommendations.md
├── accepted_recommendations.md
├── rejected_recommendations.md
└── research_questions.md
```

This reduces unnecessary repository scanning and gives every model consistent context.

The coding agents may additionally receive access to the repository itself.

---

# 4. Agent Roles Against Repository Targets

## Research Agent

Inputs:

```text
Repository Profile
+
Current Capabilities
+
Known Features
+
Previous Research
```

Research does not initially need write access to the repository.

Its objective is:

> Find potentially useful external developments relevant to this particular application.

---

## Engineering Agent

Inputs:

```text
Repository
+
Research Findings
+
Architecture Model
+
Recommendation History
```

Its objective is:

> Determine whether the proposed improvement makes sense in this actual implementation.

---

## Action Agent

Inputs:

```text
Approved Recommendation
+
Implementation Plan
+
Repository
```

Permissions are elevated only for this stage.

For example:

```yaml
permissions:
  filesystem:
    read: true
    write: true

  git:
    create_branch: true
    commit: true
    push: true

  github:
    create_pr: true

  merge:
    allowed: false
```

---

# 5. Tool Registry

Agents should access capabilities through Alena's Tool Registry rather than being given unrestricted shell/network access.

Example:

```yaml
tools:
  - id: repo.search
    version: 1
    provider: builtin

    description: Search repository contents.

    permissions:
      filesystem: read

    allowed_agents:
      - repo-analyzer
      - thinking-agent
      - codex
      - claude-code

  - id: git.diff
    version: 1
    provider: builtin

    description: Retrieve changes between commits.

    permissions:
      git: read

  - id: web.search
    version: 1
    provider: builtin

    description: Search public internet sources.

    permissions:
      network:
        internet: true

  - id: github.create_pr
    version: 1
    provider: builtin

    permissions:
      github:
        write: true

    requires_approval: true
```

---

# 6. Initial Tool Set

Alena should initially expose a relatively small but useful toolset.

## Repository Tools

```text
repo.list_files
repo.read_file
repo.search
repo.find_symbol
repo.get_structure
repo.get_languages
repo.get_frameworks
repo.get_dependencies
repo.get_tests
repo.find_todos
```

---

## Git Tools

```text
git.status
git.log
git.diff
git.show
git.branch
git.create_branch
git.commit
git.push
```

Mutation tools require higher permissions.

---

## GitHub Tools

```text
github.get_repo
github.search_code
github.get_issues
github.get_prs
github.create_issue
github.create_pr
github.comment
```

---

## Web Research Tools

```text
web.search
web.fetch
web.search_news
web.search_github
web.search_releases
web.search_documentation
```

---

## Dependency Tools

```text
dependency.scan
dependency.outdated
dependency.release_notes
dependency.security_advisories
dependency.license_check
```

---

## Code Quality Tools

```text
code.lint
code.format_check
code.typecheck
code.static_analysis
code.complexity
code.dead_code
code.duplication
```

---

## Test Tools

```text
test.detect_framework
test.run
test.run_file
test.coverage
test.failed
```

---

## Architecture Tools

```text
architecture.extract
architecture.dependencies
architecture.call_graph
architecture.api_surface
architecture.database_schema
```

---

## Intelligence Tools

```text
memory.search
memory.store
recommendation.search
recommendation.compare
research.search_previous
portfolio.search_capability
```

---

# 7. Tool Gateway

Agents should not invoke tools directly.

All calls pass through a Tool Gateway.

```text
Agent
  │
  │ tool request
  ▼
Tool Gateway
  │
  ├── Is tool registered?
  │
  ├── Is agent allowed?
  │
  ├── Is repository allowed?
  │
  ├── Are required permissions granted?
  │
  ├── Does it require human approval?
  │
  └── Log invocation
          │
          ▼
         Tool
```

This becomes a major security boundary.

---

# 8. Standard Tool Protocol

Every tool should expose a consistent contract.

Example:

```json
{
  "name": "dependency.outdated",
  "version": "1.0.0",

  "description":
    "Find outdated dependencies in the target repository.",

  "inputs": {
    "repository_id": "string"
  },

  "outputs": {
    "dependencies": "array"
  },

  "permissions": [
    "repository.read",
    "network.internet"
  ]
}
```

This makes it possible for local models, Codex, Claude, and future agents to understand the same capability catalog.

---

# 9. Tool Discovery

Agents should be able to query available tools.

Example:

```text
Agent:

I need to determine whether the application has
unused Python dependencies.

        │
        ▼

tools.search(
  "detect unused python dependencies"
)

        │
        ▼

Candidates:

dependency.scan
python.import_analysis
code.dead_code
```

The agent chooses the best existing capability before attempting to invent one.

---

# 10. Agent-Created Tools

Eventually Alena should support agents creating new tools.

This should NOT mean unrestricted self-modifying code.

Instead use a controlled lifecycle.

```text
Agent identifies repeated problem
          │
          ▼
Search Tool Registry
          │
       no tool
          │
          ▼
Tool Proposal
          │
          ▼
Tool Builder Agent
          │
          ▼
Sandbox Implementation
          │
          ▼
Tests
          │
          ▼
Security Review
          │
          ▼
Human Approval
          │
          ▼
Tool Registry
```

---

# 11. Example

Suppose agents repeatedly need to understand Django REST Framework routes.

Currently they do:

```text
read urls.py
read serializers
read viewsets
search routers
infer endpoints
```

After several runs Alena determines this operation is repetitive.

Agent proposes:

```text
Tool:
django.extract_api
```

Purpose:

> Generate a structured description of all Django REST Framework endpoints.

Implementation could use:

- Python AST;
- Django introspection;
- DRF router inspection.

Output:

```json
[
  {
    "method": "GET",
    "path": "/api/books/",
    "view": "BookViewSet",
    "serializer": "BookSerializer"
  }
]
```

Future agents now call:

```text
django.extract_api
```

instead of spending thousands of model tokens reconstructing the same information.

That is where autonomous tool creation becomes genuinely valuable.

---

# 12. Tool Proposal Schema

Agents submit proposals such as:

```yaml
tool_proposal:
  name: django.extract_api

  problem:
    Agents repeatedly reconstruct Django REST API routes
    manually.

  expected_benefit:
    - fewer tokens
    - faster repository analysis
    - deterministic results
    - improved accuracy

  expected_usage:
    weekly

  implementation_language:
    python

  required_permissions:
    - repository.read
    - process.execute

  risk:
    low
```

---

# 13. Tool Builder Agent

Introduce a specialized Tool Builder.

```text
                     Orchestrator
                          │
              Tool capability missing
                          │
                          ▼
                    Tool Builder
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
       Design Tool      Build         Tests
                          │
                          ▼
                    Tool Candidate
```

The Tool Builder may use:

```text
Local LLM
Claude Code
Codex
```

depending on complexity.

---

# 14. Generated Tool Repository

Keep tools separate from the Alena core.

Example:

```text
alena-tools/
├── builtin/
│
├── generated/
│   ├── django_extract_api/
│   │   ├── tool.yaml
│   │   ├── main.py
│   │   ├── test_main.py
│   │   └── README.md
│   │
│   └── react_route_mapper/
│
└── registry.yaml
```

This makes generated tools auditable.

---

# 15. Tool Versioning

Never allow an agent to silently overwrite an existing tool.

Instead:

```text
django.extract_api@1.0.0
django.extract_api@1.1.0
django.extract_api@2.0.0
```

The registry controls which version is active.

Example:

```yaml
django.extract_api:
  active_version: 1.1.0

  versions:
    - 1.0.0
    - 1.1.0
```

---

# 16. Tool Quality Metrics

Alena should measure tool effectiveness.

For every invocation:

```text
execution time
success
failure
token savings
agent retries
accuracy
repositories used
```

Then calculate something such as:

```text
Tool Utility Score
```

A tool that is never used can eventually be retired.

A tool that repeatedly fails can be flagged for repair.

---

# 17. Tool Improvement Loop

Tools themselves become optimization targets.

```text
Tool
 │
 ├── execution history
 ├── failures
 ├── latency
 └── agent feedback
        │
        ▼
Tool Critic
        │
        ▼
Improvement Proposal
        │
        ▼
New Version
```

Example:

```text
django.extract_api v1

fails on nested routers

        ↓

Tool Critic

        ↓

django.extract_api v1.1

adds nested router support
```

---

# 18. Tool Creation Threshold

Agents should NOT create a tool whenever they encounter a small inconvenience.

Require one or more conditions.

Example:

```text
same operation performed >= 3 times

OR

tool could reduce > 5,000 tokens/run

OR

manual approach is unreliable

OR

capability is required by >= 2 repositories

OR

operation should be deterministic
```

This prevents tool proliferation.

---

# 19. Tool Categories

Tools should be tagged.

Example:

```yaml
categories:
  - repository
  - git
  - github
  - web
  - testing
  - security
  - architecture
  - database
  - django
  - react
  - ros2
  - infrastructure
```

This will become particularly valuable because Alena operates over applications with very different technology stacks.

---

# 20. Capability Graph

Eventually represent tools and repository capabilities as a graph.

Example:

```text
LumaIndex
   │
   ├── Django
   │      │
   │      ├── django.extract_api
   │      └── django.inspect_models
   │
   ├── Postgres
   │      │
   │      └── postgres.inspect_schema
   │
   └── PDF
          │
          └── pdf.inspect_document
```

Athena might have:

```text
Athena
  │
  ├── GitHub
  │
  ├── CVE
  │     │
  │     └── security.lookup_cve
  │
  ├── Docker
  │     │
  │     └── docker.inspect_image
  │
  └── Network
```

Agents therefore receive tools appropriate to the repository rather than every tool in existence.

---

# 21. Repository-Specific Tool Policies

Repositories may also declare which tools are allowed.

Example:

```yaml
repositories:
  - id: production-control-plane

    tool_policy:
      allow:
        - repo.*
        - git.read.*
        - dependency.*
        - test.*

      deny:
        - git.push
        - infrastructure.apply
        - database.write
```

A sandbox repository may allow much more:

```yaml
tool_policy:
  allow:
    - "*"
```

---

# 22. Agent Workspace

Every run receives an isolated workspace.

```text
runs/
└── run_01J...
    ├── repo/
    ├── context/
    ├── outputs/
    ├── tools/
    └── logs/
```

Any temporary code or scripts generated by the agent stay here.

Nothing becomes a permanent Alena tool until it goes through the tool promotion process.

---

# 23. Scratch Tools vs Permanent Tools

This distinction is important.

Agents may create:

## Scratch Tool

Temporary script needed for one task.

Example:

```text
runs/.../tools/analyse_csv.py
```

It disappears after the run.

## Candidate Tool

Agent believes it has reusable value.

```text
candidate-tools/react-route-analyzer/
```

Requires evaluation.

## Registered Tool

Approved, tested reusable capability.

```text
alena-tools/generated/react_route_analyzer/
```

This provides autonomy without allowing uncontrolled code accumulation.

---

# 24. Revised Overall Architecture

```text
                   PROJECT ALENA
                        │
                 ┌──────┴──────┐
                 │ Orchestrator │
                 └──────┬──────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
 Repository        Agent Registry      Tool Registry
 Registry
        │               │                │
        └───────────────┼────────────────┘
                        │
                        ▼
                  Run Planner
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
      Local LLM    ChatGPT Work   Coding Agents
                                   │
                              ┌────┴─────┐
                              ▼          ▼
                            Codex    Claude Code
                                   │
                                   ▼
                              Tool Gateway
                                   │
        ┌────────────┬─────────────┼─────────────┐
        ▼            ▼             ▼             ▼
       Git         GitHub          Web          Tests
        │
        ▼
  Repository Tools

                        │
                        ▼
                  Thinking Agent
                        │
                        ▼
                 Recommendation
                        │
                        ▼
                   Human Gate
                        │
                        ▼
                   Action Agent

────────────────────────────────────────────────────────

             Autonomous Capability Evolution

                        Agent
                          │
                    Missing Tool
                          │
                          ▼
                    Tool Proposal
                          │
                          ▼
                    Tool Builder
                          │
                          ▼
                       Sandbox
                          │
                          ▼
                        Tests
                          │
                          ▼
                       Review
                          │
                          ▼
                    Tool Registry
```

---

# 25. Long-Term Vision

Alena starts as:

> An AI system that identifies ways to improve software.

It then evolves into:

> A software engineering system that improves how it performs software engineering.

The important progression is:

```text
Stage 1
Agents use fixed tools.

Stage 2
Agents discover which tools are useful.

Stage 3
Agents propose missing tools.

Stage 4
Agents build reusable tools.

Stage 5
Agents measure tool effectiveness.

Stage 6
Agents improve their own tools.

Stage 7
Alena develops specialized capabilities for the
technologies and repositories it repeatedly encounters.
```

The system therefore becomes more efficient over time without requiring uncontrolled recursive self-modification.

The critical boundary remains:

```text
Agents may improve capabilities.

Agents may not independently expand permissions.
```

Permissions, repository access, production access, secrets, merging, and deployment remain controlled by the orchestrator and human policy.