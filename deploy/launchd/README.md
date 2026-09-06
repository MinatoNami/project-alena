# Running ALENA's improvement loop unattended

Every trigger in the spec is a subcommand, so scheduling is `launchd` calling
`scripts/alena_improve.sh`. Nothing schedules itself from inside the
application: launchd survives reboots, and a subcommand can be re-run by hand
when a night looks wrong.

These are templates with `/Users/YOU` in them. Installing a launchd job is a
persistent change to the machine that starts running software on a timer, so
it is a decision to make deliberately -- nothing installs itself.

## Two kinds of agent

One of these is a **job**: it runs on a timer and exits. One is a **service**:
it starts at load and stays up.

| | Job | Service |
|---|---|---|
| | cycle | dashboard |
| Shape | `StartCalendarInterval`, `RunAtLoad: false` | `KeepAlive`, `RunAtLoad: true` |
| Loading it | arms the timer | starts it |

The tests assert the two shapes separately, because getting them the wrong way
round fails silently in opposite directions: a job with `RunAtLoad` does work
the moment you install it, and a service without `KeepAlive` disappears the
first time it exits.

## The cadence

One pass a night, in order:

| When | Command | What it costs |
|---|---|---|
| Always | dashboard on http://127.0.0.1:9100 | one idle Python process |
| Nightly 02:00 | `cycle --all` | one Codex call per new observation; everything else local |

`cycle` is scan → ingest whatever research has been dropped → review what is
new → score it → refresh the portfolio. It stops at the approval gate.

This used to be three jobs on three different days, which had two problems. A
research document dropped on a Thursday waited until the following Wednesday
to be reviewed, and the review of a repository was never part of the same run
as the scan that found it, so reading one log never told you what happened.

**Nightly is not more expensive than weekly was.** An unchanged repository is
skipped without reaching the model, and review costs one Codex call per *new*
observation. The bill follows how much has actually changed, not how often the
job runs. A quiet night is a scan, no new observations, and an exit.

### The Claude escalation stays off the timer

`review --all --agent claude` is the expensive reviewer, and nothing schedules
it — `test_nothing_schedules_a_live_claude_escalation` fails the build if
anything ever does. Run it with `--dry-run` for a while and read the escalation
rate before letting it call anything:

```bash
scripts/alena_improve.sh review --all --agent claude --dry-run
```

When you do want it on a timer, add it as a second job rather than to this one,
so its cost stays legible and can be turned off by itself.

## Installing one

Substitute the paths, then load it:

```bash
sed "s|/Users/YOU|$HOME|g" deploy/launchd/local.alena.cycle.plist \
  > ~/Library/LaunchAgents/local.alena.cycle.plist
mkdir -p ~/.alena/logs
launchctl load ~/Library/LaunchAgents/local.alena.cycle.plist
```

Run it once by hand before trusting the timer. `kickstart -k` starts it now,
which is the only way to find out whether it works in launchd's environment
rather than in your shell's:

```bash
launchctl kickstart -k "gui/$(id -u)/local.alena.cycle"
launchctl print "gui/$(id -u)/local.alena.cycle" | grep -E "state|last exit"
tail -f ~/.alena/logs/cycle.log
```

To check on it, and to stop it:

```bash
launchctl list | grep alena
launchctl unload ~/Library/LaunchAgents/local.alena.cycle.plist
```

### The environment a job actually gets

launchd starts a job with a bare `PATH` -- no login shell, no profile, none of
what your terminal has. `scripts/alena_improve.sh` therefore prepends
`~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin` itself. Without that
the scheduled cycle cannot find the Codex CLI, which npm installs to
`~/.local/bin`, and it fails at 02:00 with nobody watching.

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

## Research: drop a file, the cycle finds it

The nightly job reads `$ALENA_RESEARCH_DIR/<repository>/` (default
`~/alena-research/`), one directory per repository id. Anything left there is
ingested on the next pass, which is why the drop point is named by repository:
a document cannot be ingested against the wrong one by being in the wrong
place.

```bash
mkdir -p ~/alena-research/luma-index
cp ~/Downloads/luma-2026-09-10.md ~/alena-research/luma-index/
```

For a one-off against an explicit path, `ingest-research` still takes one
directly:

```bash
scripts/alena_improve.sh ingest-research luma-index ~/Downloads/luma-2026-09-10.md
```

With nothing dropped, the nightly job is a correct no-op: it scans, finds no
new observations, and exits zero.

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
