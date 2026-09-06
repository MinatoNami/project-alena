"""An HTTP endpoint that satisfies ALENA's Claude routine contract locally.

`claude_review.py` posts a prompt to `CLAUDE_ROUTINE_URL` and reads the answer
back. It was written against an assumed hosted trigger and its own docstring
says it had never been run against a live one, so the second reviewer -- the
independent half of "one model implements, the other checks" -- has never
actually run. This closes that, with the `claude` CLI already on the machine
and no API key: a small server that speaks the contract and shells out.

    POST /review  {"prompt": "...", "metadata": {...}}  ->  {"result": "..."}

Synchronous, because the call is one CLI invocation and there is nothing to
poll. The client already accepts a finished answer in the response.

## What contains the reviewer

This is the part worth reading. Codex is contained by the Tool Gateway; a
reviewer reached over HTTP is not, so containment here is whatever this file
establishes:

* **It runs in an empty directory**, never a repository. The reviewer is sent a
  diff as *text* and asked to judge it. Running it inside a checkout would give
  a model that has just been handed untrusted research text a working tree to
  act on.
* **Tools are denied.** `--permission-prompts none` denies anything that would
  prompt, and the writing and fetching tools are named explicitly. A reviewer
  needs to read the prompt and answer; nothing else.
* **Loopback only, with an optional shared token.** The endpoint runs a model
  on request, so it is not something to expose.
* **Bounded**: prompt size, output size, and a wall-clock timeout, so one
  request cannot hang the reviewer for every later one.
"""

from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple

from modules.core.controller.logger import logger

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9200
DEFAULT_TIMEOUT = 600

MAX_PROMPT_CHARS = 200_000
MAX_OUTPUT_CHARS = 100_000

# A reviewer reads the prompt and answers. Anything that reaches the machine or
# the network is denied by name, and `--permission-prompts none` denies
# whatever else would have asked.
DENIED_TOOLS = (
    "Bash", "Edit", "Write", "NotebookEdit",
    "WebFetch", "WebSearch", "Task", "Read", "Glob", "Grep",
)


def workspace() -> Path:
    """An empty directory to run in, created if absent.

    Deliberately not a repository. The reviewer is handed a diff as text; a
    checkout would be an invitation.
    """
    directory = Path(
        os.getenv("CLAUDE_ROUTINE_WORKSPACE") or "~/.alena/routine-workspace"
    ).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_claude(prompt: str, timeout: int = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """Ask the local CLI, with tools denied. Returns (ok, text)."""
    command = [
        "claude",
        "-p",
        "--permission-prompts",
        "none",
        "--output-format",
        "text",
        "--disallowed-tools",
        *DENIED_TOOLS,
    ]
    try:
        process = subprocess.run(
            command,
            input=prompt[:MAX_PROMPT_CHARS],
            cwd=str(workspace()),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "the `claude` CLI is not on PATH"
    except subprocess.TimeoutExpired:
        return False, f"the reviewer did not answer within {timeout}s"

    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[:600]
        return False, f"claude exited {process.returncode}: {detail}"

    answer = (process.stdout or "").strip()[:MAX_OUTPUT_CHARS]
    if not answer:
        return False, "the reviewer returned nothing"
    return True, answer


class Handler(BaseHTTPRequestHandler):
    server_version = "alena-routine-shim"

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        expected = (os.getenv("CLAUDE_ROUTINE_TOKEN") or "").strip()
        if not expected:
            return True
        header = self.headers.get("Authorization", "")
        return header.removeprefix("Bearer ").strip() == expected

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        if self.path.rstrip("/") == "/health":
            self._send(200, {"status": "ok", "workspace": str(workspace())})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            self._send(401, {"error": "unauthorised"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "body must be JSON"})
            return

        prompt = str((payload or {}).get("prompt") or "").strip()
        if not prompt:
            self._send(400, {"error": "a prompt is required"})
            return

        kind = str(((payload or {}).get("metadata") or {}).get("kind") or "review")
        logger.info(f"routine shim: {kind}, {len(prompt)} characters")

        ok, text = run_claude(prompt)
        if not ok:
            logger.warning(f"routine shim failed: {text}")
            # A shape the client understands as failure rather than an answer.
            self._send(502, {"status": "failed", "error": text})
            return

        self._send(200, {"status": "completed", "result": text})

    def log_message(self, format: str, *args: Any) -> None:
        """Through ALENA's logger, not stderr, so launchd's log is one stream."""
        logger.info(f"routine shim: {format % args}")


def serve(host: str = "", port: int = 0) -> None:
    host = host or os.getenv("CLAUDE_ROUTINE_HOST") or DEFAULT_HOST
    port = port or int(os.getenv("CLAUDE_ROUTINE_PORT") or DEFAULT_PORT)

    if host not in {"127.0.0.1", "localhost", "::1"}:
        # This endpoint runs a model on request. Binding it beyond loopback is
        # a decision nobody should make by leaving a variable set.
        raise SystemExit(
            f"refusing to bind {host}: the routine shim is loopback-only. "
            "Put a reverse proxy in front of it if you really mean to expose it."
        )

    logger.info(f"routine shim on http://{host}:{port}/review  cwd={workspace()}")
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
