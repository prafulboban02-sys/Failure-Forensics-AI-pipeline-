"""
Single place that configures the LangChain <-> LLM connection.
Every pipeline step imports get_llm() rather than instantiating its own
client, so swapping providers/models/temperature later is a one-line change.

Supports two providers, switchable via LLM_PROVIDER in .env:
  - "ollama"    : free, runs locally, no API key needed (current default)
  - "anthropic" : Claude via the Anthropic API (swap to this later)

IMPORTANT DESIGN NOTE: get_llm() accepts an optional `prefix` so the
judge (Phase 3 root-cause analysis) can use a DIFFERENT provider/model
than the pipeline itself. This matters because if the judge is the same
model as the thing it's judging, it shares the same blind spots -- it
won't catch a mistake it would have made itself. Best practice for
LLM-as-judge is to use a stronger or at least different model as the judge.

To use Claude as the judge while keeping the pipeline on free local Ollama,
set in .env:
    JUDGE_LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    JUDGE_MODEL=claude-sonnet-5
(Leave LLM_PROVIDER=ollama untouched -- only the judge switches.)
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0.0, prefix: str = ""):
    """
    prefix="" (default): used by pipeline steps. Reads LLM_PROVIDER,
        OLLAMA_MODEL, PIPELINE_MODEL.
    prefix="JUDGE_": used by the judge. Reads JUDGE_LLM_PROVIDER (falls
        back to LLM_PROVIDER if unset), JUDGE_OLLAMA_MODEL (falls back to
        OLLAMA_MODEL), JUDGE_MODEL (falls back to PIPELINE_MODEL).
    """
    provider = os.getenv(f"{prefix}LLM_PROVIDER", os.getenv("LLM_PROVIDER", "ollama")).lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        model = os.getenv(f"{prefix}OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "llama3.1"))
        return ChatOllama(model=model, temperature=temperature)

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env, or switch "
                f"{prefix}LLM_PROVIDER back to 'ollama' in .env."
            )
        model = os.getenv(f"{prefix}MODEL", os.getenv("PIPELINE_MODEL", "claude-sonnet-5"))
        return ChatAnthropic(
            model=model, temperature=temperature, api_key=api_key, max_tokens=1024
        )

    else:
        raise RuntimeError(
            f"Unknown {prefix}LLM_PROVIDER '{provider}'. Use 'ollama' or 'anthropic'."
        )
