"""Tool contracts and side-effect classification.

A *contract* is what a tool is: its name, its schemas, what it does to the
world. It comes from the tool itself -- ideally from MCP `tools/list`, which
the Tool Interoperability Standard makes the canonical description.

A *policy* (see policy.py) is who may call it, against which repository, and
whether a human has to say yes first. The two are kept apart on purpose: the
protocol describes how to call a tool, ALENA decides whether it may be called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SideEffect(Enum):
    """What a tool does to the world.

    Ordered least to most consequential. The gateway compares ranks, so the
    order of declaration matters -- new values go in the right place, not the
    end.
    """

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    REPOSITORY_WRITE = "repository_write"
    REMOTE_WRITE = "remote_write"
    INFRASTRUCTURE_CHANGE = "infrastructure_change"
    DESTRUCTIVE = "destructive"

    @property
    def rank(self) -> int:
        return _SIDE_EFFECT_ORDER.index(self)

    def at_least(self, other: "SideEffect") -> bool:
        """True if this side effect is at least as consequential as `other`."""
        return self.rank >= other.rank

    @classmethod
    def parse(cls, value: str) -> "SideEffect":
        try:
            return cls(value)
        except ValueError:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"Unknown side effect {value!r}. Expected one of: {allowed}"
            ) from None


_SIDE_EFFECT_ORDER = [
    SideEffect.READ_ONLY,
    SideEffect.LOCAL_WRITE,
    SideEffect.REPOSITORY_WRITE,
    SideEffect.REMOTE_WRITE,
    SideEffect.INFRASTRUCTURE_CHANGE,
    SideEffect.DESTRUCTIVE,
]


@dataclass(frozen=True)
class ToolContract:
    """A tool as the tool itself describes it.

    `side_effect` is the one field MCP does not carry natively. It is supplied
    by policy, or inferred from MCP annotations as a fallback; see
    discovery.side_effect_hint for why the inference only ever guesses upward.
    """

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    version: str = "1.0.0"
    mcp_server: Optional[str] = None
    source: str = "static"
    # What the server's own MCP annotations imply, if anything. A hint only:
    # policy decides, this exists so a disagreement can be spotted.
    side_effect_hint: Optional["SideEffect"] = None

    def required_arguments(self) -> list[str]:
        required = self.input_schema.get("required", [])
        return list(required) if isinstance(required, list) else []

    def validate_arguments(self, arguments: Dict[str, Any]) -> None:
        """Check the arguments carry every required property.

        Not full JSON Schema validation -- the tool itself does that, and
        duplicating it here would be a second source of truth. This catches the
        common model error of omitting a required field, before a subprocess is
        spawned to find out.
        """
        if not isinstance(arguments, dict):
            raise ValueError(f"Arguments for {self.name} must be an object")
        missing = [key for key in self.required_arguments() if key not in arguments]
        if missing:
            raise ValueError(
                f"Missing argument(s) for {self.name}: {', '.join(sorted(missing))}"
            )

    def to_openai_tool(self) -> Dict[str, Any]:
        """Render for an OpenAI-compatible `tools` array (LM Studio)."""
        parameters = self.input_schema or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }
