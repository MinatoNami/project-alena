"""A minimal MCP server used by the gateway tests.

Real enough to exercise the whole path -- a subprocess, a stdio transport, an
initialize handshake, tools/list and tools/call -- without needing the Codex
CLI or network access. `fake_pid` is what proves session reuse: two calls that
report the same pid came from the same process.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("fake-mcp")


@mcp.tool()
def fake_echo(text: str) -> str:
    """Echo the text back."""
    return f"echo:{text}"


@mcp.tool()
def fake_pid() -> str:
    """Report the server process id."""
    return str(os.getpid())


@mcp.tool()
def fake_boom() -> str:
    """Always fail, so error handling has something to handle."""
    raise RuntimeError("fake_boom always fails")


@mcp.tool()
def fake_read(repo_path: str) -> str:
    """Take a path argument, so path checks have something to check."""
    return f"read:{repo_path}"


if __name__ == "__main__":
    mcp.run()
