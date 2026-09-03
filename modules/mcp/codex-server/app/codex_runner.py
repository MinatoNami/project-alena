import subprocess
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
        [
            "--sandbox",
            SANDBOX_WORKSPACE_WRITE if apply_mode else SANDBOX_READ_ONLY,
        ]
    )

    process = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, cwd=cwd, check=False
    )

    if process.returncode != 0:
        raise RuntimeError(process.stderr)

    return process.stdout
