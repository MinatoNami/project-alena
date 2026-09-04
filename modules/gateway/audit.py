"""Audit log for tool invocations.

Every call through the gateway is recorded -- including the ones that were
refused. Denials are the more interesting half: they are how you find out that
an agent keeps reaching for a capability it does not have, which is the signal
the tool-proposal lifecycle is supposed to act on.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from modules.store import get_connection

# Argument values that should never reach durable storage even when argument
# logging is switched on.
_REDACT_KEYS = {
    "token", "api_key", "apikey", "password", "secret",
    "authorization", "credentials", "private_key",
}
_REDACTED = "***"


def hash_arguments(arguments: Dict[str, Any]) -> str:
    """A stable fingerprint of a call's arguments.

    Used instead of the arguments themselves: they routinely carry file
    contents and can carry credentials, and a durable log of those is a
    liability. The hash still answers "was this exact call made before".
    """
    try:
        canonical = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-redact obviously sensitive keys."""
    if not isinstance(arguments, dict):
        return {}
    return {
        key: (_REDACTED if key.lower() in _REDACT_KEYS else value)
        for key, value in arguments.items()
    }


def _arguments_enabled() -> bool:
    return os.getenv("ALENA_AUDIT_ARGUMENTS", "0") == "1"


@dataclass(frozen=True)
class InvocationRecord:
    tool: str
    agent: str
    outcome: str  # success | denied | error
    arguments_hash: str
    tool_version: Optional[str] = None
    mcp_server: Optional[str] = None
    repository_id: Optional[str] = None
    side_effect: Optional[str] = None
    arguments: Optional[str] = None
    denial_reason: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class AuditLog:
    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        # Resolved lazily so importing the gateway does not create a database.
        if self._conn is None:
            self._conn = get_connection()
        return self._conn

    def record(
        self,
        *,
        tool: str,
        agent: str,
        outcome: str,
        arguments: Dict[str, Any],
        tool_version: Optional[str] = None,
        mcp_server: Optional[str] = None,
        repository_id: Optional[str] = None,
        side_effect: Optional[str] = None,
        denial_reason: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> int:
        stored_arguments = (
            json.dumps(redact(arguments), sort_keys=True, default=str)
            if _arguments_enabled()
            else None
        )
        cursor = self.conn.execute(
            """
            INSERT INTO tool_invocations (
                created_at, tool, tool_version, mcp_server, agent,
                repository_id, side_effect, arguments_hash, arguments,
                outcome, denial_reason, duration_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                tool,
                tool_version,
                mcp_server,
                agent,
                repository_id,
                side_effect,
                hash_arguments(arguments),
                stored_arguments,
                outcome,
                denial_reason,
                duration_ms,
                error,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM tool_invocations ORDER BY id DESC LIMIT ?", (limit,)
            )
        )

    def count(self, outcome: Optional[str] = None) -> int:
        if outcome is None:
            row = self.conn.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM tool_invocations WHERE outcome = ?", (outcome,)
            ).fetchone()
        return int(row[0])
