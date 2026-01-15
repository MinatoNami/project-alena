import json

def normalize_codex_output(content):
    messages = []
    reasoning = []

    for chunk in content:
        if not hasattr(chunk, "text"):
            continue

        for line in chunk.text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "item.completed":
                continue

            item = event.get("item", {})
            if item.get("type") == "agent_message":
                messages.append(item.get("text", ""))
            elif item.get("type") == "reasoning":
                reasoning.append(item.get("text", ""))

    return {
        "message": "\n\n".join(messages).strip(),
        "reasoning": "\n\n".join(reasoning).strip() or None,
    }
