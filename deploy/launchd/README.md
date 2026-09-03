# Running ALENA's improvement loop unattended

Every trigger in the spec is a subcommand, so scheduling is `launchd` calling
`scripts/alena_improve.sh`. Nothing schedules itself from inside the
application: launchd survives reboots, and a subcommand can be re-run by hand
when a night looks wrong.

**Nothing here is installed for you.** These are templates. Installing a
launchd job is a persistent change to your machine that starts running
software on a timer, so it is a decision to make deliberately.

## The cadence

Matching the spec's weekly workflow:

| When | Command | What it costs |
|---|---|---|
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

Edit the paths in a plist, then:

```bash
cp deploy/launchd/local.alena.scan.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/local.alena.scan.plist
```

To check on it, and to stop it:

```bash
launchctl list | grep alena
launchctl unload ~/Library/LaunchAgents/local.alena.scan.plist
```

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
