"""
Token usage reporting differs slightly across LangChain chat model
providers (and Ollama sometimes omits it entirely for local models).
This helper extracts it defensively so tracing never crashes a pipeline
run just because a provider didn't report tokens.
"""

from typing import Optional


def get_token_usage(response) -> tuple[Optional[int], Optional[int]]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None, None
    return usage.get("input_tokens"), usage.get("output_tokens")
