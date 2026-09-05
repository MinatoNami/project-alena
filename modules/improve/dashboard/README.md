# alena-improve dashboard

Nuxt 4 + Tailwind, over a FastAPI adapter. Five pages: status, the approval
queue, repositories, portfolio, tool metrics.

```bash
scripts/start_alena_dashboard.sh          # dev, hot reload on 3100
scripts/start_alena_dashboard.sh --serve  # one process on 9100
```

`--serve` is what runs in the background: the API serves the built dashboard
from its own port, so there is one Python process, no node, and the browser
is same-origin. Build it first, and again after any UI change:

```bash
cd modules/improve/dashboard && npm install && npm run generate
```

To have it always running, see
[deploy/launchd](../../../deploy/launchd/README.md) — it installs as a
service rather than a scheduled job.

## It is a third adapter, not a third implementation

`modules/improve/web/api.py` calls the same functions the CLI and the MCP
server call — `query.py`, `status.py`, `decide.py`. No endpoint contains
logic, and if one grows past shaping a result, that belongs in the query
layer. This is the same discipline that made the MCP server thin, and it is
why a whole web app was a day rather than a rewrite.

## Loopback, and why that is not enough on its own

The API can approve a recommendation, and an approved recommendation is what
authorises the action agent to write to a repository. So both processes bind
to `127.0.0.1`.

That handles the network but not the browser. A page on the public internet
cannot *read* a loopback response, but it can *send* a simple cross-origin
POST to one — drive-by approval is a real shape of attack against any
localhost service that changes state. Two things close it:

- Origins are allowlisted, and only the dashboard's own are on the list.
- Every state-changing request must carry `X-Alena-Dashboard`. A custom header
  forces a CORS preflight, and an unlisted origin fails that preflight — so
  the POST never arrives, rather than arriving and being refused afterwards.

There is no login, because there is no second user. If you ever bind this off
loopback, that stops being true and it needs one.

## Running a step

The status page has a button for the whole nightly pass — **Run a cycle** —
and one per individual step: scan, review, recommend, a Claude escalation
preview, and a portfolio refresh. Output streams back into the page.

"Run a cycle" is the same command the nightly job runs, so re-running a night
by hand is one button rather than four in the right order. The individual
steps are for when you know which one you want.

Each one starts a **subprocess running the same wrapper launchd runs**, so a
button and a timer take an identical path — including the PATH fixes and the
`.env` sourcing that only exist in that script. Nothing is reimplemented for
the browser.

**One at a time.** They share a database and the same workspaces, and two
scans racing would interleave writes for nothing. A second request is refused
with a 409 rather than queued: queueing would let a stray double-click spend a
second Codex review.

A `$` on a button means it spends beyond local compute. Only `review` does —
one Codex call per new observation. A button that quietly costs quota is one
people regret.

Runs are held in memory, so a restart forgets them, and the scheduled jobs run
the same commands without appearing in the list. It is a view of what you
started from here, not a history of everything that ran.

## Proposing something

A form for an idea of your own. It enters the pipeline where research does and
is treated the same: de-duplicated, reviewed, scored, and brought back for
your decision.

The reviewer is told the proposal came from you and is asked for judgement
rather than agreement — the failure mode for an operator's own idea is a
reviewer that rubber-stamps it, so the prompt explicitly invites "no".

## Watching a run

Output streams into the page while the work happens. Codex emits JSONL events
as it goes -- the commands it runs, the files it changes -- and those are
turned into short lines and written to the MCP server's **stderr**, which the
CLI inherits and the run panel captures. Stdout is the MCP protocol channel;
progress there would corrupt every message on it.

Everything is flushed explicitly and both subprocess layers run unbuffered.
Python block-buffers when its output is a pipe rather than a terminal, which
is exactly the case here, and unflushed progress arrives in one lump at the
end -- which is the thing this is for.

```
codex: $ /bin/zsh -lc 'npm install nuxt@^4.0.0'
codex:   exit 1
codex: changed package.json
codex: done — 1398677 in, 8449 out
```

Reasoning is not shown. It is the bulk of the output and it is the model
thinking aloud rather than anything happening.

**Restarting the dashboard kills a run in progress.** Runs are subprocesses
of the API, so `launchctl kickstart` takes them with it. A killed run never
reaches its own cleanup and leaves its branch checked out with uncommitted
work; `alena-improve implement <repo> <id> --recover` discards that and
starts again, and the next run recognises the situation rather than blaming
the mess on you.

## Steering a run

The run panel has a text box. What you type is appended to the analysis as
`--focus`, and reaches the agent framed as an instruction from you — not as
material to evaluate, which is how research text is framed. That difference is
the point: treating your steer as data makes it useless, and treating research
as instructions is the injection path the review exists to contain.

It applies to Scan and Review. Buttons that have no use for it refuse it
rather than dropping it, so a steer never silently disappears.

## Implementing

There is a button, on the accepted recommendation itself rather than in the
row of portfolio-wide buttons — a command that acts on one repository does
not belong somewhere a stray click reaches it. It asks for confirmation, and
the confirmation says which repository is about to be written to.

Four things have to be true before anything is written, and **none of them
lives in the dashboard**:

| Gate | Where it lives |
|---|---|
| `modify` and `create_branch` for that repository | `config/repositories.yaml` |
| The recommendation is `accepted` | a recorded human decision |
| The working tree is completely clean | the action agent's pre-flight |
| A scoped, expiring write grant | the Tool Gateway |

The API checks the first two itself so a mistake in the browser is an
immediate readable refusal rather than something that surfaces in log output
forty seconds later. The CLI checks them all again, because a scheduled or
terminal run never passes through here.

All four registered repositories are read-only today, so the button refuses
with a message saying exactly which flag to set and where. The dashboard
cannot set it.

Nothing is pushed and nothing is merged. What comes back is a branch, a
commit, the tests it could run, and an independent review of the diff.

`ingest-research` has no button — it needs a file path, and a browser should
not be choosing one.

## Pages

| Page | What it answers |
|---|---|
| Status | What is waiting at each hand-off, what is stalled, did the scheduled jobs run |
| Queue | What is proposed, the evidence, both reviewers' verdicts — accept or reject |
| Repositories | Profile, summary, languages, recommendation history |
| Portfolio | Divergent pins, shared dependencies, work that might travel |
| History | Every scan, ingest, review, decision and implementation, by day |
| Research | Every document, expandable, with what came out of it |
| Propose | An idea of your own, entering where research does |
| Tools | Effectiveness from the audit log |

The status page refreshes every 30 seconds, because the numbers move when a
scheduled job runs and a tab left open overnight should not lie.

Rejecting requires a reason, and the form says why: the reason reaches the
context package and the next reviewer's prompt, and without one the same idea
returns with nothing to recognise it by. The API enforces it regardless of
what the form does.

## Ports

| | |
|---|---|
| API | 9100 (`ALENA_DASHBOARD_PORT`) |
| Nuxt dev | 3100 (`devServer` in `nuxt.config.ts`) |

Those two have to agree with `allowed_origins()` in `api.py`. They did not at
first, and the symptom is a dashboard that loads and then reports it cannot
reach the API — the CORS preflight fails, so the response is never readable.
