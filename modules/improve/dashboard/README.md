# alena-improve dashboard

Nuxt 4 + Tailwind, over a FastAPI adapter. Five pages: status, the approval
queue, repositories, portfolio, tool metrics.

```bash
scripts/start_alena_dashboard.sh        # API on 9100, Nuxt on 3100
scripts/start_alena_dashboard.sh --api  # just the API
```

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

## Implementing is not something a browser does

There is no implement endpoint. It writes to a repository, takes minutes, and
is the thing most worth watching while it happens. Accepting in the dashboard
prints the command instead:

```
alena-improve implement luma-index 3
```

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
