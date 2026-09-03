"""Local-model summaries of a repository and its recent changes.

Every summary here is optional. The nightly scan runs unattended against every
repository; if LM Studio is asleep, the scan must still produce its structural
output -- file counts, dependencies, TODO deltas -- rather than failing the
whole run over a model that was not loaded. So each function returns None on
failure and the caller carries on.
"""

from __future__ import annotations

import os
from typing import Optional

from modules.core.controller.logger import logger
from modules.llm import LLMChatClient, LLMConfig, LLMUnavailable

MAX_SUMMARY_WORDS = 200


def _client() -> LLMChatClient:
    return LLMChatClient(
        LLMConfig(
            base_url=os.getenv("LLM_BASE_URL", "http://localhost:1234"),
            model=os.getenv("LLM_MODEL", ""),
            timeout_s=float(os.getenv("LLM_TIMEOUT", "120")),
            debug=os.getenv("LLM_DEBUG", "0") == "1",
        )
    )


def _ask(prompt: str, system: str, client: Optional[LLMChatClient] = None) -> Optional[str]:
    try:
        # Building the client is inside the guard too: a bad LLM_BASE_URL
        # should cost the summary, not the whole nightly run.
        client = client or _client()
        reply = client.chat([{"role": "user", "content": prompt}], system_prompt=system)
    except LLMUnavailable as exc:
        logger.warning(f"Summary skipped, inference unavailable: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 - a summary is never worth a failed scan
        logger.warning(f"Summary failed: {exc!r}")
        return None
    return reply.strip() or None


_REPO_SYSTEM = (
    "You summarise software repositories for an engineering audience that has "
    "not read the code. Be concrete and factual. Do not speculate about "
    "features you cannot see, and do not recommend anything."
)

_DIFF_SYSTEM = (
    "You summarise git changes for an engineering audience. Say what changed "
    "and why it plausibly changed, in past tense. Do not recommend anything."
)


def summarize_repository(
    *,
    name: str,
    languages: dict,
    dependencies: list,
    file_count: int,
    readme: Optional[str] = None,
    recent_subjects: Optional[list] = None,
    note: Optional[str] = None,
    client: Optional[LLMChatClient] = None,
) -> Optional[str]:
    """A short profile of what this repository is.

    `note` is a steer the operator typed for this run -- "we are considering
    moving storage off Postgres, say what depends on it". It comes from the
    person running ALENA, so it is an instruction, not something to evaluate.
    """
    top_languages = ", ".join(f"{k} ({v} files)" for k, v in list(languages.items())[:6])
    top_dependencies = ", ".join(d["name"] for d in dependencies[:40])
    commits = "\n".join(f"- {s}" for s in (recent_subjects or [])[:15])

    prompt = f"""Summarise this repository in at most {MAX_SUMMARY_WORDS} words.

Repository: {name}
Files tracked: {file_count}
Languages: {top_languages or "unknown"}
Declared dependencies: {top_dependencies or "none found"}

Recent commit subjects:
{commits or "(none)"}

README (truncated):
{(readme or "(no README found)")[:4000]}

Cover: what the project does, its architecture in broad strokes, and the
technologies it commits to. State only what the evidence above supports.
{f"{chr(10)}Your operator asked you to pay particular attention to this:{chr(10)}{note.strip()}" if (note or "").strip() else ""}"""
    return _ask(prompt, _REPO_SYSTEM, client)


def summarize_changes(
    *,
    name: str,
    diff_stat: str,
    commit_subjects: list,
    diff: str = "",
    client: Optional[LLMChatClient] = None,
) -> Optional[str]:
    """What moved since the last scan."""
    if not diff_stat and not commit_subjects:
        return None

    subjects = "\n".join(f"- {s}" for s in commit_subjects[:30])
    prompt = f"""Summarise what changed in {name} since the previous scan, in at
most {MAX_SUMMARY_WORDS} words.

Commits:
{subjects or "(none)"}

Diff stat:
{diff_stat or "(none)"}

Diff (truncated):
{diff[:8000] or "(not included)"}

Group related changes. Call out anything that looks like an architectural or
dependency change."""
    return _ask(prompt, _DIFF_SYSTEM, client)
