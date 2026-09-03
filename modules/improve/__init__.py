"""ALENA's autonomous codebase improvement orchestrator.

Separate from the assistant's agent loop: this analyses *other* repositories
and produces reviewed recommendations. It shares modules/llm, modules/store and
the Tool Gateway, and nothing else.
"""
