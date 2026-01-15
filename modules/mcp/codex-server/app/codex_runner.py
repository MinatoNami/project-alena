import subprocess
import json
from typing import Optional

CODEX_BIN = "codex"  # must be in PATH

def run_codex(
    prompt: str,
    cwd: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> str:
    cmd = [
        CODEX_BIN,
        "exec",
        "--json"
    ]

    if extra_args:
        cmd.extend(extra_args)

    process = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False
    )

    if process.returncode != 0:
        raise RuntimeError(process.stderr)

    return process.stdout
