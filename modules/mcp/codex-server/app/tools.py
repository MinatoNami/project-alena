from mcp.server.fastmcp import FastMCP
from app.codex_runner import run_codex

mcp = FastMCP("codex-mcp")

@mcp.tool()
def codex_generate(prompt: str) -> str:
    """
    Generate code using Codex CLI.
    """
    return run_codex(prompt)

@mcp.tool()
def codex_edit(repo_path: str, instruction: str) -> str:
    """
    Edit code in a repository using Codex.
    """
    return run_codex(
        instruction,
        cwd=repo_path,
        extra_args=["--apply"]
    )
