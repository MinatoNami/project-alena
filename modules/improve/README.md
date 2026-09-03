# alena-improve

The autonomous codebase improvement orchestrator. Separate from the assistant's
agent loop: this analyses *other* repositories and produces reviewed
recommendations. It shares `modules/llm`, `modules/store` and the Tool Gateway,
and nothing else.

Status: **Phase 1** — repository intelligence. Nothing here calls a cloud agent
or writes to a repository yet.

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
```

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
├── registry/       repositories.yaml -> Repository, resolution, capabilities
├── scan/           git, dependencies, TODOs, fingerprint
├── intelligence/   LM Studio summaries (best-effort)
├── persistence.py  SQLite reads and writes
├── artifacts.py    alena-intelligence/ layout and markdown rendering
├── scan_run.py     one repository scan
├── wiring.py       registry -> gateway allowed roots
└── cli.py          alena-improve
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
