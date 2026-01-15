import anyio
from types import SimpleNamespace

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

import json
from typing import List


def normalize_codex_output(content: List) -> dict:
    """
    Normalize Codex CLI MCP output into clean text.

    Returns:
        {
            "message": str,      # main response
            "reasoning": str | None
        }
    """
    messages = []
    reasoning = []

    for chunk in content:
        if not hasattr(chunk, "text"):
            continue

        # Codex streams newline-delimited JSON
        for line in chunk.text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "item.completed":
                continue

            item = event.get("item", {})
            item_type = item.get("type")

            if item_type == "agent_message":
                messages.append(item.get("text", ""))

            elif item_type == "reasoning":
                reasoning.append(item.get("text", ""))

    return {
        "message": "\n\n".join(messages).strip(),
        "reasoning": "\n\n".join(reasoning).strip() or None,
    }



SERVER = SimpleNamespace(
    command="python",
    args=["-m", "app.main"],
    cwd=None,
    env=None,
    encoding="utf-8",
    encoding_error_handler="replace",
    name="codex-mcp",
)


async def main():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            # REQUIRED MCP handshake
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:")
            for name, _ in tools:
                print(" -", name)


            result = await session.call_tool(
                "codex_generate",
                {"prompt": "Hello there! Introduce yourself in a few sentences."},
            )

            normalized = normalize_codex_output(result.content)

            print("\n🧠 Codex reasoning:")
            print(normalized["reasoning"] or "(none)")

            print("\n🛠 Codex response:")
            print(normalized["message"])



if __name__ == "__main__":
    anyio.run(main)
