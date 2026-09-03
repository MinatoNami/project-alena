# alena-improve

The autonomous codebase improvement orchestrator. Separate from the assistant's
agent loop: this analyses *other* repositories and produces reviewed
recommendations. It shares `modules/llm`, `modules/store` and the Tool Gateway,
and nothing else.

Status: **Phase 2** — research ingest and Codex engineering review. Nothing
here writes to a repository.

## The registry is the authority

Agents are never handed a filesystem path they chose themselves. Every run
starts by resolving a declared target through `config/repositories.yaml`:

```
alena-improve scan luma-index
        │
        ▼
  Repository Registry
        │
        ├── unknown  → refuse
        ├── disabled → refuse
        ├── capability not granted → refuse
        │
        └── resolved workspace  ──►  scan
```

The registry's workspaces are also what the gateway accepts as path arguments
(`modules/improve/wiring.py`). That is the real answer to the question
`safety.py` tried to answer with one hardcoded path.

Capability defaults are asymmetric on purpose:

| | Default | Why |
|---|---|---|
| `research`, `analyze`, `plan` | `true` | A repository you registered is one you want looked at |
| `modify`, `create_branch`, `create_pr` | `false` | The cost of guessing wrong runs one way |
| `merge` | `false`, and cannot become true by omission | Unrecoverable |

The loader refuses anything token-shaped anywhere in the file. The registry is
checked in, so it is exactly the file someone will paste a token into.

## The scan

Trigger B from the spec — the nightly local pass, LM Studio only.

```
git state ──► fingerprint ──► changed?
                                 │
                        no ──────┴────── yes
                         │                │
                       skip          languages, dependencies,
                    (no model)       TODO delta, summaries
                                          │
                                          ▼
                              SQLite + alena-intelligence/
```

The fingerprint covers HEAD, the branch **and** the working tree, because a
repository sitting on uncommitted work has moved even though HEAD has not. An
unchanged repository costs a handful of git commands and never reaches the
model — which is the point, since the nightly run touches every repository
whether or not anything happened.

Summaries are best-effort. An unattended run must still produce its structural
output when LM Studio is asleep, so a summary failure is logged and the scan
continues.

TODO deltas key on `path + marker + text`, deliberately not the line number: a
TODO that moved because something above it changed is the same TODO, and
counting it as resolved-and-reintroduced every night would drown the signal.

## The weekly loop

```
ChatGPT Work (its own schedule)
        │  research/<repo>/<date>.md
        ▼
   ingest-research ──► observations ──► dedup ──► skipped if already proposed
        │
        ▼
     review  ──► Codex, read-only, through the gateway
        │
        ▼
   recommend  ──► scored ──► recommendations/<repo>/latest.md
                                │
                        rejected by review
                                │
                     recorded, so it is recognised next time
```

### Research is untrusted input

The research document is written by an external agent reading the public
internet, and it ends up in front of a coding agent. See
[the contract](../../Documents/RESEARCH_DOCUMENT_CONTRACT.md) for the full
reasoning; the short version is that the gateway is what contains it. The
review runs as agent `codex`, whose tool policy grants read-only tools only,
so a hijacked review still cannot write. Prompt framing is the third line of
defence, not the first.

### De-duplication

Three layers, checked at ingest rather than after review, because reviewing a
proposal that was already turned down is the expensive half of the mistake:

| Layer | Catches | Needs |
|---|---|---|
| Normalized title | Reordering and rewording of the heading | nothing |
| Token overlap | Near-verbatim restatement | nothing |
| Embedding cosine | Genuine paraphrase | an embedding model loaded |

LM Studio serves embeddings only when an embedding model occupies its
embedding slot, which is separate from the chat slot. With that slot empty —
the usual state of an install set up for chat — layers 1 and 2 still run, and
a genuine paraphrase can reach review. What catches it then is the
rejected-recommendations file in the context package, which goes into the
reviewer prompt with the reason each idea was turned down. Set
`LLM_EMBEDDING_MODEL` and load one to close the gap properly.

### Scoring

The spec's weights, as data in `recommend/scoring.py` so they can later be
fitted to acceptance history. Evidence and novelty are derived rather than
judged — evidence counts what the document actually cited, novelty is one
minus similarity to something already proposed. The rest come from the review.

A missing dimension defaults to 0.5, not 0: a candidate whose review failed
should land mid-table where a human sees it, not at the bottom where nobody
looks.

## The approval gate

Nothing becomes code without a recorded human decision.

```
recommend ──► recommended ──┬──► accepted ──┬──► implemented ──┬──► successful
                            │               │                  ├──► unsuccessful
                            │               └──► abandoned      └──► abandoned
                            └──► rejected ──► (revisit) ──► recommended
```

The transitions are a closed set, not an UPDATE anyone can make, and decisions
are appended rather than overwritten — "accepted, then abandoned three weeks
later" is a different fact from "abandoned", and only one of them survives an
overwrite.

A rejection or an abandonment **requires** a reason. That is not paperwork: the
reason goes into the context package, the next reviewer's prompt, and
de-duplication. A rejection without one means the same idea arrives next month
with nothing to recognise it by.

The report's `[ ] Accept` block stays a view. `alena-improve decide` is what
records anything.

## The action agent

The only thing in ALENA that writes to a repository, and every one of these has
to hold before it starts:

| Gate | Why |
|---|---|
| `capabilities.modify` and `create_branch` in the registry | opt-in per repository |
| recommendation status is `accepted` | a human said so |
| working tree completely clean, untracked files included | the commit stages everything |
| a fresh `alena/<id>-<slug>` branch | the base branch is never committed to |

### Permission lasts one run

Accepting a recommendation issues an `ActionGrant`: scoped to one repository,
capped at `repository_write`, carrying the recommendation id as its authority,
and dropped in a `finally` when the run ends. A grant that outlives its run is
a standing write permission nobody remembers issuing.

Two limits make a grant safe to hand out. It **satisfies** the approval the
policy demands; it never adds a tool the policy would refuse — an agent outside
`allowed_agents` stays refused with a grant in hand. And it is **capped at
`repository_write`**, so it can authorise a branch and a commit but never a
push, a pull request, an infrastructure change or anything destructive. Those
leave the machine or cannot be undone, and each needs its own explicit human
act rather than riding along with "yes, implement this".

Approval is now per agent in `tool_policy.yaml`. A user asking the assistant to
edit a file *is* the approval; an autonomous run needs an accepted
recommendation. Same tool, different answer:

```yaml
codex_edit:
  allowed_agents: ["assistant", "action-agent"]
  requires_approval: ["action-agent"]
```

### Nothing is pushed

There is no push and no pull-request step. The agent leaves a branch with a
commit, the tests it could run, and an independent review of the diff. Merging
is yours.

### Cross review

The spec wants the opposite model to review, so no model both proposes and
blesses its own work. Writing to a repository means running a tool on this
machine through the gateway, and the only agent wired that way is Codex — a
Claude routine can read a diff but cannot commit to a workspace here. So the
pairing is currently fixed rather than alternating: **Codex implements, Claude
reviews.** The independent-check property holds, which is the part that
matters, and `action/routing.py` is data so the rotation starts working when
Claude gains a local write path.

### On failure, nothing is left behind

A failed run reverts tracked files, removes what the agent created, returns to
the base branch and deletes its own branch. Removing untracked files is safe
*because* of the pre-flight check: the tree was completely clean before the run,
so anything untracked afterwards is the agent's own output. The implementation
row is written before any of this, so a half-finished branch can still be found.

## Commands

```bash
scripts/alena_improve.sh scan --all          # nightly pass
scripts/alena_improve.sh scan luma-index     # one repository
scripts/alena_improve.sh scan --all --force  # ignore the fingerprint
scripts/alena_improve.sh scan --all --no-llm # structure only, no summaries
scripts/alena_improve.sh repos               # what is declared
scripts/alena_improve.sh show luma-index     # the latest scan
scripts/alena_improve.sh audit               # recent gateway invocations
scripts/alena_improve.sh where               # which files are actually in use

scripts/alena_improve.sh context luma-index                    # write .context/
scripts/alena_improve.sh ingest-research luma-index r.md       # take a report
scripts/alena_improve.sh ingest-research luma-index --from-dir ~/drop
scripts/alena_improve.sh review luma-index                     # Codex, read-only
scripts/alena_improve.sh recommend luma-index                  # score and report

scripts/alena_improve.sh pending                               # awaiting a decision
scripts/alena_improve.sh decide luma-index 3 --accept
scripts/alena_improve.sh decide luma-index 4 --reject --reason "too early"
scripts/alena_improve.sh implement luma-index 3                # writes a branch
scripts/alena_improve.sh trail luma-index 3                    # what happened
scripts/alena_improve.sh decide luma-index 3 --successful \
    --actual-effort LARGE --observed-value 0.8
```

The last one closes the loop the spec asks for: estimated against actual
effort, expected against observed value. None of it can be recovered after the
fact, and it is what the scoring weights get fitted to later.

Every trigger is a subcommand rather than a scheduler inside the application:
launchd survives reboots, a subcommand can be re-run by hand when something
looks wrong, and the same entry point is what the tests call.

Nightly, via launchd:

```xml
<key>ProgramArguments</key>
<array>
  <string>/Users/you/git-repos/project-alena/scripts/alena_improve.sh</string>
  <string>scan</string>
  <string>--all</string>
</array>
<key>StartCalendarInterval</key>
<dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
```

## Where things live

| | Default | Override |
|---|---|---|
| Registry | `config/repositories.yaml` | `ALENA_REPOSITORIES` |
| Workspace root | *(unset)* | `ALENA_WORKSPACE_ROOT` |
| Database | `~/.alena/alena.db` | `ALENA_DB_PATH` |
| Generated artifacts | `~/.alena/intelligence` | `ALENA_INTELLIGENCE_DIR` |

`alena-improve where` prints the resolved paths, which is the first thing to
check when a run reads the wrong config.

## Layout

```
modules/improve/
├── registry/          repositories.yaml -> Repository, resolution, capabilities
├── scan/              git, dependencies, TODOs, fingerprint
├── intelligence/      LM Studio summaries (best-effort)
├── research/          parse and ingest external research
├── agents/            Codex engineering review, through the gateway
├── recommend/         dedup, scoring, synthesis, markdown
├── action/            the action agent, cross-review routing, test running
├── decide.py          the approval gate and its state machine
├── text.py            shared normalisation (owned by neither, to avoid a cycle)
├── context_package.py the .context/ bundle every agent reads
├── persistence.py     SQLite reads and writes
├── artifacts.py       alena-intelligence/ layout and markdown rendering
├── scan_run.py        one repository scan
├── review_run.py      review and recommend orchestration
├── wiring.py          registry -> gateway allowed roots
└── cli.py             alena-improve
```

Capabilities are plain functions with typed inputs and outputs and no MCP
imports. That is what keeps the Phase 5 MCP server a thin adapter rather than a
rewrite — logic inside an `@mcp.tool()` body cannot be called from the CLI, a
worker, or a unit test.

## Tests

```bash
pytest modules/improve -v
```

The scanner tests run against a real git repository built in `tmp_path`. A
faked `git` would only prove the fake behaves as expected.
