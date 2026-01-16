import subprocess
import json
from typing import Optional

CODEX_BIN = "codex"  # must be in PATH


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

    if apply_mode:
        cmd.extend(
            [
                "--full-auto",
                "--sandbox",
                "workspace-write",
            ]
        )

    process = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, cwd=cwd, check=False
    )

    if process.returncode != 0:
        raise RuntimeError(process.stderr)

    return process.stdout
