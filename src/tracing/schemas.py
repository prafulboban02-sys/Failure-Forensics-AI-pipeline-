"""
A Span is the atomic unit of forensic evidence: one pipeline step, one
execution. Everything the Phase 3 root-cause analyzer needs to diagnose a
failure lives here — nothing is reconstructed after the fact.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Any
from pydantic import BaseModel, Field


class Span(BaseModel):
    span_id: str
    trace_id: str          # shared across all spans in one pipeline run
    doc_id: str
    step_name: str          # "intake" | "extraction" | "classification" | "summarization"
    source_filename: str

    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)

    prompt: Optional[str] = None          # system prompt used for this step's LLM call
    raw_llm_response: Optional[str] = None

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0

    confidence: Optional[int] = Field(default=None, ge=1, le=5)  # normalized 1-5

    status: str = "ok"       # "ok" | "error"
    error_message: Optional[str] = None

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
