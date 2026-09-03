"""Gateway refusals.

Every denial carries a stable `reason_code`: it is written to the audit log and
counted, so it must not be prose someone later rewords.
"""

from __future__ import annotations

from typing import Optional


class GatewayError(Exception):
    """Base class for everything the gateway raises."""

    reason_code = "gateway_error"


class GatewayDenied(GatewayError):
    """The call was refused before any tool ran."""

    reason_code = "denied"

    def __init__(self, message: str, reason_code: Optional[str] = None):
        super().__init__(message)
        if reason_code:
            self.reason_code = reason_code


class ToolNotRegistered(GatewayDenied):
    reason_code = "tool_not_registered"


class ToolNotDeclared(GatewayDenied):
    reason_code = "tool_not_declared"


class InvalidArguments(GatewayDenied):
    reason_code = "invalid_arguments"


class ApprovalRequired(GatewayDenied):
    reason_code = "approval_required"


class RepositoryPathDenied(GatewayDenied):
    reason_code = "repository_path_denied"
