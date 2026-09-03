# Project Alena — Autonomous Codebase Improvement System

## 1. Objective

Build a local-first autonomous system that continuously analyzes software repositories, researches relevant external developments, identifies opportunities for improvement, validates those opportunities against the actual codebase, and produces prioritized Markdown recommendations.

The system should:

- Understand the current state of each repository.
- Detect meaningful changes between runs.
- Research new technologies, releases, competitors, features, patterns, and vulnerabilities.
- Identify missing or potentially valuable capabilities.
- Avoid repeatedly suggesting previously rejected ideas.
- Compare opportunities across the entire application portfolio.
- Use multiple independent AI systems to challenge recommendations.
- Keep humans in the loop before source-code modifications are made.
- Generate a persistent history of recommendations and outcomes.

---

# 2. Core Principle

Project Alena acts as the orchestrator.

Individual AI systems are specialized workers.

```text
                         PROJECT ALENA
                              │
                       Local Orchestrator
                              │
       ┌──────────────────────┼───────────────────────┐
       │                      │                       │
       ▼                      ▼                       ▼
  LM Studio             ChatGPT Work           Coding Agents
 Local Models             Research              │
       │                      │              ┌────┴────┐
       │                      │              ▼         ▼
       │                      │            Codex   Claude Code
       │                      │
       └──────────────────────┼───────────────────────┘
                              │
                              ▼
                    Recommendation Engine
                              │
                              ▼
                       Human Approval
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
                Reject                  Approve
                  │                       │
                  ▼                       ▼
                Memory              Action Agent
                                          │
                                    Draft PR / Issue
```

No external AI provider should own the workflow.

This allows providers to be changed or replaced later.

---

# 3. AI Responsibilities

## 3.1 Local LLM — LM Studio

Primary machine:

**MacBook M5 Max — 128 GB**

Responsibilities:

- Repository classification
- Repository summaries
- Git diff summarization
- Dependency extraction
- Architecture extraction
- Code indexing
- Embedding generation
- Previous recommendation retrieval
- Duplicate recommendation detection
- Initial feature ideation
- Recommendation classification
- Recommendation scoring
- Report preprocessing

Local models should handle tasks that are:

- frequent;
- relatively deterministic;
- high-volume;
- inexpensive to verify.

The M5 Max should therefore perform the majority of inference.

---

## 3.2 ChatGPT Work — Research Agent

ChatGPT Work acts primarily as Alena's external research and product-intelligence system.

Responsibilities:

- Web research
- Competitor analysis
- Product feature discovery
- Emerging technology research
- Open-source project discovery
- Framework ecosystem research
- Industry trends
- Product strategy
- Cross-domain research

Example research request:

> Research developments from the last 30 days that could materially improve LumaIndex.
>
> Investigate ebook readers, document management systems, PDF tooling, AI document understanding, semantic search, OCR, browser APIs and relevant open-source projects.
>
> Do not recommend implementation yet.
>
> Produce evidence-backed observations.

Expected output:

```text
research/
└── luma-index/
    └── 2026-09-03.md
```

ChatGPT Work should primarily answer:

> What has changed outside our repository that we should know about?

It should not be the primary coding agent.

---

# 4. Codex — OpenAI Engineering Agent

Codex operates against repositories.

Responsibilities:

- Codebase analysis
- Architecture validation
- Technical feasibility analysis
- Dependency analysis
- Refactoring opportunities
- Test analysis
- Implementation planning
- CI investigation
- Issue creation
- Implementation
- Draft PR generation

Codex answers:

> Given the actual implementation, does this recommendation make engineering sense?

Example:

```text
Research observation:

"Semantic document search may significantly improve
large personal libraries."

                  ↓

                Codex

                  ↓

Inspect LumaIndex

                  ↓

Determine:

- existing search architecture
- database impact
- indexing requirements
- affected modules
- migration requirements
- implementation complexity
```

Codex should reject recommendations that do not fit the repository.

---

# 5. Claude Code — Independent Engineering Reviewer

Claude Code should deliberately overlap partially with Codex.

This is intentional.

Its main role is independent technical review.

Responsibilities:

- Deep repository analysis
- Architecture review
- Challenge Codex conclusions
- Identify hidden implementation risks
- Alternative implementation proposals
- Security implications
- Technical debt analysis
- Implementation planning
- Optional implementation after approval

Claude should answer:

> Is Codex's engineering assessment actually correct?

Example:

```text
              Recommendation
                    │
                    ▼
                  Codex
                    │
            Technical Proposal
                    │
                    ▼
              Claude Code
                    │
        Independent Criticism
                    │
           ┌────────┴────────┐
           ▼                 ▼
        Agree             Disagree
           │                 │
           └────────┬────────┘
                    ▼
             Final Assessment
```

Using two different frontier coding systems reduces the chance that a plausible but weak architectural idea survives simply because one model proposed and reviewed its own work.

---

# 6. Thinking / Synthesis Agent

The Thinking Agent combines:

- Repository intelligence
- ChatGPT research
- Codex engineering analysis
- Claude engineering analysis
- Historical recommendations
- User feedback

It produces the final recommendation.

Example scoring dimensions:

| Dimension | Meaning |
|---|---|
| Value | Expected user/product value |
| Evidence | Strength of external evidence |
| Fit | Compatibility with current architecture |
| Novelty | Whether this is genuinely new |
| Cost | Estimated implementation cost |
| Risk | Engineering/operational risk |
| Confidence | Confidence across reviewing agents |

Example:

```text
Overall Score =

30% Value
20% Architectural Fit
15% Evidence
15% Novelty
10% Confidence
- 5% Cost
- 5% Risk
```

The exact weights should eventually be adjusted using historical acceptance/rejection data.

---

# 7. Trigger Architecture

There should be several trigger classes.

## Trigger A — Git Change

Event:

```text
push / merge
```

Flow:

```text
GitHub
   │
   ▼
Alena
   │
   ▼
git diff
   │
   ▼
Local LLM
   │
   ▼
Update repository intelligence
```

This does NOT trigger expensive research automatically.

It only updates Alena's understanding of the repository.

---

# 8. Trigger B — Nightly Local Analysis

Schedule:

```text
Every night
```

Example:

```text
02:00
```

Triggered using:

- cron
- launchd
- APScheduler

Responsibilities:

- pull repositories;
- detect changed branches;
- refresh dependency information;
- update repository summaries;
- update embeddings;
- identify TODO/FIXME changes;
- check stale recommendations;
- perform lightweight analysis.

Primary execution:

```text
LM Studio
```

No Claude/ChatGPT call should normally be required.

---

# 9. Trigger C — Weekly Research

Schedule:

```text
Wednesday morning
```

Trigger:

**ChatGPT Work Scheduled Task**

Purpose:

Perform external research for repositories where Alena has detected meaningful changes or where research has become stale.

Research:

- competitor developments;
- framework releases;
- new open-source projects;
- emerging AI capabilities;
- ecosystem changes;
- product patterns;
- relevant browser/platform capabilities.

Output:

```text
research/YYYY-MM-DD.md
```

ChatGPT Work is selected because this is primarily a research and synthesis task rather than a coding task.

---

# 10. Trigger D — Codex Engineering Review

Schedule:

```text
After weekly research
```

Possible trigger:

**Codex Automation**

Example cadence:

```text
Wednesday evening
```

Codex reads:

```text
repository intelligence
+
research report
+
previous recommendations
```

Codex then validates recommendations against the repository.

Output:

```text
engineering/codex/YYYY-MM-DD.md
```

No implementation should occur during this stage.

---

# 11. Trigger E — Claude Code Engineering Review

Preferred trigger:

**Alena API trigger**

Claude Code Routines provide a dedicated HTTP trigger.

Conceptually:

```text
Alena
   │
   │ HTTP POST
   ▼
Claude Code Routine
   │
   ▼
Engineering Review
```

Trigger Claude when:

```text
recommendation.score >= threshold

OR

recommendation.requires_architecture_review == true

OR

codex.confidence < threshold

OR

recommendation.security_sensitive == true

OR

recommendation.estimated_effort >= LARGE
```

This is preferable to running Claude against every observation.

Example:

```text
40 research observations
          │
          ▼
      Local filtering
          │
          ▼
    10 candidates
          │
          ▼
        Codex
          │
          ▼
     4 candidates
          │
          ▼
     Claude Code
```

This conserves Claude Code subscription usage.

---

# 12. Claude Code Routine Triggers

Claude Code currently supports three particularly useful trigger types.

## Scheduled

Example:

```text
Every Thursday at 02:00
```

Useful for:

- weekly architecture review;
- documentation drift;
- technical-debt review.

## GitHub Event

Example:

```text
PR opened
PR updated
```

Useful for:

- architecture-sensitive changes;
- security-sensitive modules;
- important repositories.

## HTTP/API

Preferred for Alena.

```text
Alena
   │
   ▼
Claude Routine API
```

This allows Alena to decide whether Claude is actually needed.

Example conditions:

```python
if candidate.score > 0.80:
    trigger_claude(candidate)

if codex_disagreement:
    trigger_claude(candidate)

if candidate.architecture_change:
    trigger_claude(candidate)
```

---

# 13. ChatGPT Work Triggers

ChatGPT Work supports scheduled and event-triggered tasks.

For Alena, the primary trigger should initially be:

## Scheduled Research

```text
Every Wednesday
```

Task:

> Research meaningful external developments relevant to the registered Alena applications.

ChatGPT Work can also react to supported connected-app events.

For example:

```text
GitHub PR activity
        │
        ▼
ChatGPT Work
        │
        ▼
Research relevant technologies
```

However, this should not be the primary mechanism initially.

Research rarely needs to happen on every commit or PR.

The weekly scheduled research run provides a better cost/value balance.

---

# 14. Codex Triggers

Codex has its own Automation system.

Use Codex Automations for repository-oriented scheduled work.

Examples:

```text
Weekly architecture scan

Daily CI failure review

Dependency migration review

Test coverage review

Issue triage
```

For Alena:

```text
Wednesday 22:00

Read latest Alena research.

Inspect each affected repository.

Produce engineering assessments.

DO NOT modify source code.
```

---

# 15. Recommended Weekly Workflow

```text
MONDAY–TUESDAY

Develop normally

Git pushes
     │
     ▼
Local Alena index updates


WEDNESDAY
────────────────────────────────────

09:00

ChatGPT Work
     │
     ▼
External research
     │
     ▼
research.md


22:00

Codex Automation
     │
     ▼
Repository engineering review
     │
     ▼
codex-review.md


THURSDAY
────────────────────────────────────

02:00

Alena evaluates Codex results
     │
     ▼
Select high-value candidates
     │
     ▼
Claude Code Routine
     │
     ▼
Independent engineering review
     │
     ▼
claude-review.md


THURSDAY MORNING

Alena Thinking Agent
     │
     ▼
Synthesize everything
     │
     ▼
recommendations.md
```

---

# 16. Recommendation Output

Example:

```text
alena-intelligence/
├── repositories/
│   ├── luma-index/
│   ├── text-whisperer/
│   ├── athena/
│   └── health-app/
│
├── research/
│   └── 2026-09-03/
│
├── engineering/
│   ├── codex/
│   └── claude/
│
├── recommendations/
│   ├── 2026-09-03.md
│   └── latest.md
│
└── memory/
```

Final recommendation format:

```markdown
## Semantic Library Search

Priority: HIGH
Confidence: 91%
Estimated Effort: MEDIUM

### Research Evidence

ChatGPT identified...

### Current Architecture

Local analysis found...

### Codex Assessment

Technically feasible because...

### Claude Assessment

Agrees with Codex but recommends...

### Proposed Architecture

...

### Affected Components

...

### Risks

...

### Implementation Plan

...

### Decision

[ ] Accept
[ ] Reject
[ ] Revisit
```

---

# 17. Human Approval Gate

No recommendation automatically becomes production code.

Flow:

```text
Recommendation
      │
      ▼
Human Review
      │
 ┌────┴────┐
 ▼         ▼
Reject   Approve
 │         │
 ▼         ▼
Memory   Implementation
```

Rejected recommendations require a reason.

Example:

```text
status: rejected
reason: too much complexity for current product maturity
```

This becomes future context.

---

# 18. Implementation Trigger

After approval:

```text
recommendation.status = APPROVED
```

Alena creates an implementation task.

The implementation agent can be either:

```text
Codex
```

or:

```text
Claude Code
```

Preferably rotate or select based on the task.

Example:

```text
Frontend feature
      ↓
Codex

Large architectural refactor
      ↓
Claude Code

Security-sensitive feature
      ↓
Claude implementation
      +
Codex review
```

Implementation produces:

```text
branch
+
tests
+
draft PR
```

Never:

```text
direct push → main
```

---

# 19. PR Review

Use the opposite model to review implementation.

If:

```text
Claude implemented
```

then:

```text
Codex reviews
```

If:

```text
Codex implemented
```

then:

```text
Claude reviews
```

Therefore:

```text
Recommendation
      │
      ▼
Human Approval
      │
      ▼
Claude Code
Implementation
      │
      ▼
Draft PR
      │
      ▼
Codex
Review
      │
      ▼
Human Merge
```

or the reverse.

This creates independent checks.

---

# 20. Self-Learning Memory

Alena records outcomes.

For each recommendation:

```text
recommended
accepted
rejected
implemented
abandoned
successful
unsuccessful
```

Store:

```text
reason
estimated effort
actual effort
expected value
observed value
agent confidence
human feedback
```

Future analysis retrieves this information.

Therefore Alena gradually learns:

- what kinds of features are usually accepted;
- what architectural changes are disliked;
- what implementation costs are underestimated;
- what repositories share useful capabilities;
- what types of recommendations produce value.

The AI models themselves are not retrained initially.

The "learning" occurs through persistent structured memory and retrieval.

---

# 21. Portfolio Intelligence

Alena should eventually analyze applications collectively.

Example:

```text
Text Whisperer
      │
      │ Whisper service
      ▼
Shared Capability Registry
      ▲
      │ voice food logging
      │
Health App
```

Alena can recommend:

> Reuse Text Whisperer's transcription service rather than introducing a second Whisper implementation.

Similarly:

```text
Athena
   │
background workers
   │
   ▼
Shared infrastructure
   ▲
   │
LumaIndex indexing
```

This turns Alena into a portfolio-level architecture intelligence system rather than merely a feature recommendation bot.

---

# 22. Phase 1

Build only:

```text
Repository scanner
        +
Git change detector
        +
LM Studio integration
        +
Recommendation memory
        +
Markdown generator
```

No autonomous cloud agents.

---

# 23. Phase 2

Add:

```text
ChatGPT Work
     │
External research

Codex Automation
     │
Engineering analysis
```

---

# 24. Phase 3

Add:

```text
Claude Code Routine API
```

Alena decides when Claude review is justified.

---

# 25. Phase 4

Add:

```text
Human approval
      │
      ▼
Implementation Agent
      │
      ▼
Draft PR
      │
      ▼
Independent AI Review
```

---

# 26. Phase 5

Add portfolio intelligence:

```text
All repositories
       │
       ▼
Shared Capability Graph
       │
       ▼
Cross-project recommendations
```

At this stage, Project Alena becomes the intelligence and orchestration layer across the entire software portfolio.