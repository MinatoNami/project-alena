from mcp.server.fastmcp import FastMCP
from app.codex_runner import run_codex
from textwrap import dedent
from typing import Optional

mcp = FastMCP("codex-mcp")


def _format_repo_prompt(
    repo_path: str,
    instruction: str,
    *,
    mode: str,
    constraints: Optional[str] = None,
    include_plan: bool = False,
) -> str:
    constraint_block = f"\nConstraints:\n{constraints}\n" if constraints else ""
    plan_block = (
        "\nProvide a concise, step-by-step plan before any changes.\n"
        if include_plan
        else ""
    )
    return dedent(
        f"""
        You are working inside the repository at: {repo_path}
        Mode: {mode}
        {plan_block}
        {constraint_block}
        Instruction:
        {instruction}
        """
    ).strip()


@mcp.tool()
def codex_generate(prompt: str) -> str:
    """
    Generate code using Codex CLI.
    """
    return run_codex(prompt)


@mcp.tool()
def codex_plan(repo_path: str, goal: str) -> str:
    """
    Produce a multi-step plan and file-level strategy for a complex task.
    """
    prompt = _format_repo_prompt(
        repo_path,
        goal,
        mode="planning",
        include_plan=True,
        constraints=(
            "Do not modify files. Provide a plan, list likely files to inspect or change, "
            "and call out risks or unknowns."
        ),
    )
    return run_codex(prompt, cwd=repo_path)


@mcp.tool()
def codex_analyze(repo_path: str, question: str) -> str:
    """
    Analyze the repository to answer a design or implementation question.
    """
    prompt = _format_repo_prompt(
        repo_path,
        question,
        mode="analysis",
        constraints=(
            "Do not modify files. Keep the answer concise and reference relevant files."
        ),
    )
    return run_codex(prompt, cwd=repo_path)


@mcp.tool()
def codex_summarize(repo_path: str, focus: Optional[str] = None) -> str:
    """
    Summarize the repository or a specific focus area.
    """
    focus_text = f"Focus: {focus}\n" if focus else ""
    prompt = _format_repo_prompt(
        repo_path,
        f"{focus_text}Provide a concise summary of the repository.",
        mode="summarize",
        constraints=("Do not modify files. Keep the summary short and actionable."),
    )
    return run_codex(prompt, cwd=repo_path)


@mcp.tool()
def codex_doc_outline(repo_path: str, topic: str, audience: str = "developers") -> str:
    """
    Draft a documentation outline for a given topic and audience.
    """
    prompt = _format_repo_prompt(
        repo_path,
        (
            f"Create a documentation outline for: {topic}. "
            f"Target audience: {audience}."
        ),
        mode="docs",
        constraints=(
            "Do not modify files. Provide an outline with section headings and bullet points."
        ),
    )
    return run_codex(prompt, cwd=repo_path)


@mcp.tool()
def codex_test_plan(repo_path: str, goal: str) -> str:
    """
    Produce a test plan for validating a feature or change.
    """
    prompt = _format_repo_prompt(
        repo_path,
        f"Create a test plan for: {goal}.",
        mode="test-plan",
        constraints=(
            "Do not modify files. Include test areas, scenarios, and acceptance criteria."
        ),
    )
    return run_codex(prompt, cwd=repo_path)


@mcp.tool()
def codex_edit(repo_path: str, instruction: str) -> str:
    """
    Edit code in a repository using Codex.
    """
    prompt = _format_repo_prompt(
        repo_path,
        instruction,
        mode="apply",
        constraints=(
            "Make only necessary edits. Preserve existing style and APIs unless required. "
            "If uncertain, choose the least invasive change."
        ),
    )
    return run_codex(
        prompt,
        cwd=repo_path,
        extra_args=["--apply"],
    )


@mcp.tool()
def codex_refactor(repo_path: str, goal: str, constraints: Optional[str] = None) -> str:
    """
    Perform a multi-file refactor with optional constraints.
    """
    prompt = _format_repo_prompt(
        repo_path,
        goal,
        mode="refactor",
        constraints=((constraints + "\n") if constraints else "")
        + "Provide a brief summary of changes at the end.",
    )
    return run_codex(prompt, cwd=repo_path, extra_args=["--apply"])
