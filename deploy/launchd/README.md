# Running ALENA's improvement loop unattended

Every trigger in the spec is a subcommand, so scheduling is `launchd` calling
`scripts/alena_improve.sh`. Nothing schedules itself from inside the
application: launchd survives reboots, and a subcommand can be re-run by hand
when a night looks wrong.

These are templates with `/Users/YOU` in them. Installing a launchd job is a
persistent change to the machine that starts running software on a timer, so
it is a decision to make deliberately -- nothing installs itself.

## Two kinds of agent

Three of these are **jobs**: they run on a timer and exit. One is a
**service**: it starts at load and stays up.

| | Jobs | Service |
|---|---|---|
| | scan, review, recommend | dashboard |
| Shape | `StartCalendarInterval`, `RunAtLoad: false` | `KeepAlive`, `RunAtLoad: true` |
| Loading it | arms the timer | starts it |

The tests assert the two shapes separately, because getting them the wrong way
round fails silently in opposite directions: a job with `RunAtLoad` does work
the moment you install it, and a service without `KeepAlive` disappears the
first time it exits.

## The cadence

Matching the spec's weekly workflow:

| When | Command | What it costs |
|---|---|---|
| Always | dashboard on http://127.0.0.1:9100 | one idle Python process |
| Nightly 02:00 | `scan --all` | local only; unchanged repositories skip the model |
| Wednesday | *(ChatGPT Work's own schedule writes research)* | — |
| Wednesday 22:00 | `ingest-research <repo> --from-dir ~/alena-research` | local only |
| Wednesday 22:30 | `review --all` | one Codex call per new observation |
| Thursday 02:00 | `review --all --agent claude` | one routine call per escalated candidate |
| Thursday 07:00 | `recommend --all` then `portfolio` | local only |

The Claude step is the expensive one. Run it with `--dry-run` first for a week
and read the escalation rate before letting it call anything:

```bash
scripts/alena_improve.sh review --all --agent claude --dry-run
```

## Installing one

Substitute the paths, then load it:

```bash
sed "s|/Users/YOU|$HOME|g" deploy/launchd/local.alena.scan.plist \
  > ~/Library/LaunchAgents/local.alena.scan.plist
mkdir -p ~/.alena/logs
launchctl load ~/Library/LaunchAgents/local.alena.scan.plist
```

Run it once by hand before trusting the timer. `kickstart -k` starts it now,
which is the only way to find out whether it works in launchd's environment
rather than in your shell's:

```bash
launchctl kickstart -k "gui/$(id -u)/local.alena.scan"
launchctl print "gui/$(id -u)/local.alena.scan" | grep -E "state|last exit"
tail -f ~/.alena/logs/scan.log
```

To check on it, and to stop it:

```bash
launchctl list | grep alena
launchctl unload ~/Library/LaunchAgents/local.alena.scan.plist
```

### The environment a job actually gets

launchd starts a job with a bare `PATH` -- no login shell, no profile, none of
what your terminal has. `scripts/alena_improve.sh` therefore prepends
`~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin` itself. Without that
a scheduled `review` cannot find the Codex CLI, which npm installs to
`~/.local/bin`, and it fails at 22:30 on a Wednesday with nobody watching.

`ALENA_WORKSPACE_ROOT` is set per job in `EnvironmentVariables` rather than in
a `.env`, so installing a schedule does not quietly change what an interactive
run is allowed to touch.

## The dashboard

A service, not a job. Build it once, then load it:

```bash
cd modules/improve/dashboard && npm install && npm run generate
sed "s|/Users/YOU|$HOME|g" deploy/launchd/local.alena.dashboard.plist \
  > ~/Library/LaunchAgents/local.alena.dashboard.plist
launchctl load ~/Library/LaunchAgents/local.alena.dashboard.plist
```

It runs `--serve`: one Python process on 9100, serving both the API and the
built dashboard. Nothing node-shaped runs at all. `npm run dev` is a file
watcher with hot reload, which is the right thing for working on the UI and
the wrong thing to leave running in the background forever.

Because one process serves both, the browser is same-origin and CORS is not
involved. That only applies to the built path; `npm run dev` runs on its own
port and does rely on the allowlist.

`KeepAlive` brings it back if it dies, throttled to 30 seconds so a startup
crash does not spin. Rebuild after changing the UI:

```bash
cd modules/improve/dashboard && npm run generate
launchctl kickstart -k "gui/$(id -u)/local.alena.dashboard"
```

## Research is still a manual step

There is no template for `ingest-research`. It takes one repository at a time,
and the ChatGPT Work output arrives however you fetch it, so a timer would be
guessing at both. The weekly rhythm is:

```bash
scripts/alena_improve.sh ingest-research luma-index ~/Downloads/luma-2026-09-10.md
```

Until something is ingested, the Wednesday and Thursday jobs are correct
no-ops -- they run, find no new observations, and exit zero.

## Before you turn any of it on

- `scripts/alena_improve.sh where` — confirm it resolves the config you expect.
  A scheduled job starts in a different directory from your shell, which is
  the usual reason a night reads the wrong registry.
- Set `ALENA_WORKSPACE_ROOT`. The registry's workspaces become the gateway's
  allowed tool paths; pinning the root means a typo cannot widen them.
- Run each command by hand once. The logs go to `/tmp` by default, and a job
  that fails silently at 02:00 is worse than no job.

## What it will never do on its own

`implement` is deliberately absent from every schedule. It writes to a
repository, and it requires a recorded human acceptance first — putting it on
a timer would mean the approval gate had a way around it.
