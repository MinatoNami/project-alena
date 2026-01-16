from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MemoryMessage:
    role: str
    content: str
    created_at: float


class ConversationMemory:
    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self._messages: List[MemoryMessage] = []

    def add(self, role: str, content: str) -> None:
        if not content:
            return
        self._messages.append(
            MemoryMessage(role=role, content=content, created_at=time.time())
        )
        self._trim()

    def add_user(self, content: str) -> None:
        self.add("user", content)

    def add_assistant(self, content: str) -> None:
        self.add("assistant", content)

    def add_tool_call(self, tool: str, arguments: Dict) -> None:
        payload = f"Tool call: {tool} | arguments: {arguments}"
        self.add("assistant", payload)

    def add_tool_result(self, tool: str, result: str) -> None:
        payload = f"Tool result: {tool} | {result}"
        self.add("assistant", payload)

    def get_messages(self) -> List[Dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self._messages]

    def clear(self) -> None:
        self._messages.clear()

    def _trim(self) -> None:
        if self.max_messages <= 0:
            self._messages.clear()
            return
        if len(self._messages) <= self.max_messages:
            return
        overflow = len(self._messages) - self.max_messages
        if overflow > 0:
            self._messages = self._messages[overflow:]


def get_default_memory() -> ConversationMemory:
    max_messages = int(os.getenv("ALENA_MEMORY_MAX_MESSAGES", "20"))
    return ConversationMemory(max_messages=max_messages)
