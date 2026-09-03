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

The status page has a button per pipeline step: scan, review, recommend, a
Claude escalation preview, and a portfolio refresh. Output streams back into
the page.

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
