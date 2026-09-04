"""Running the Codex CLI, and saying what it is doing while it does it.

Codex emits JSONL events as it works -- the commands it runs, the files it
changes -- and a long edit can take many minutes. Capturing all of that and
returning it at the end leaves anyone watching with a blank screen and no way
to tell a slow run from a stuck one.

So the output is read line by line and a short human line is written to
**stderr** as each event arrives. Stderr specifically: stdout is the MCP
protocol channel, and writing progress there would corrupt every message on
it. The MCP client passes the server's stderr through to its own, which the
CLI inherits and the dashboard's run panel captures -- so a line printed here
reaches a browser a second or so later.

Every write is flushed. Python block-buffers stderr when it is a pipe rather
than a terminal, which is exactly the case here, and unflushed progress
arrives in one lump at the end -- the problem this is meant to solve.
"""

import json
import subprocess
import sys
from typing import Optional

CODEX_BIN = "codex"  # must be in PATH

# Sandbox modes, passed explicitly on every call.
#
# Read-only is stated rather than left to the default: it is defence in depth
# for the analysis tools, so a read tool cannot write even if something above
# it went wrong. Workspace-write is the widest this ever asks for -- nothing
# here uses danger-full-access.
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"

MAX_PROGRESS_CHARS = 160


def _progress(message: str) -> None:
    print(f"  codex: {message}"[:MAX_PROGRESS_CHARS], file=sys.stderr, flush=True)


def describe_event(line: str) -> Optional[str]:
    """A short human line for one Codex JSONL event, or None to stay quiet.

    Reasoning is deliberately dropped: it is the bulk of the output and it is
    the model thinking aloud, not something happening.
    """
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, dict):
        return None

    kind = event.get("type")
    item = event.get("item") or {}
    item_type = item.get("type")

    if kind == "item.started" and item_type == "command_execution":
        return f"$ {item.get('command', '')}"
    if kind == "item.completed" and item_type == "command_execution":
        code = item.get("exit_code")
        return f"  exit {code}" if code else None
    if kind == "item.completed" and item_type == "file_change":
        changes = item.get("changes") or []
        paths = ", ".join(c.get("path", "").split("/")[-1] for c in changes)
        return f"changed {paths}"
    if kind == "item.completed" and item_type == "agent_message":
        first = (item.get("text") or "").strip().splitlines()
        return first[0] if first else None
    if kind == "turn.completed":
        usage = event.get("usage") or {}
        return (
            f"done — {usage.get('input_tokens', 0)} in, "
            f"{usage.get('output_tokens', 0)} out"
        )
    return None


def run_codex(
    prompt: str,
    cwd: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> str:
    apply_mode = False
    cleaned_args: list[str] = []
    if extra_args:
        for arg in extra_args:
            if arg == "--apply":
                apply_mode = True
            else:
                cleaned_args.append(arg)

    cmd = [CODEX_BIN, "exec", "--json"]
    if cleaned_args:
        cmd.extend(cleaned_args)

    # `--full-auto` was removed in codex-cli 0.153. `exec` is already
    # non-interactive, so the sandbox mode is the whole of what it meant.
    cmd.extend(
        ["--sandbox", SANDBOX_WORKSPACE_WRITE if apply_mode else SANDBOX_READ_ONLY]
    )

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )

    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()

    # Accumulated in full for the caller, which parses the same JSONL for the
    # final answer. Streaming is additional, not a replacement.
    captured: list[str] = []
    for line in process.stdout:
        captured.append(line)
        described = describe_event(line)
        if described:
            _progress(described)

    stderr = process.stderr.read() if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError(stderr or "codex exited non-zero with no message")

    return "".join(captured)
