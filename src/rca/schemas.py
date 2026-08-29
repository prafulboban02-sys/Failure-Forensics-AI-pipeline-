"""
Schemas for Phase 3: root-cause analysis.

The core idea: an LLM-as-judge scores each step's output quality given
what it received as input. The FIRST step in pipeline order whose quality
drops below an acceptable threshold is the root cause — everything after
it is likely just propagating that step's damage forward.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    EXTRACTION_HALLUCINATION = "extraction_hallucination"
    MISCLASSIFICATION = "misclassification"
    PROPAGATION_ERROR = "propagation_error"
    CONTEXT_LOSS = "context_loss"
    VERIFIED_ERROR = "verified_error"  # caught by a DETERMINISTIC check, not the judge's opinion
    NONE = "none"  # step is fine


class JudgeVerdict(BaseModel):
    step_name: str
    quality_score: int = Field(ge=1, le=5)
    category: FailureCategory
    reasoning: str
    specific_issues: list[str] = Field(default_factory=list)


class RootCauseReport(BaseModel):
    trace_id: str
    doc_id: str
    source_filename: str

    root_cause_step: Optional[str] = None
    root_cause_category: FailureCategory = FailureCategory.NONE
    root_cause_explanation: str = ""

    step_verdicts: list[JudgeVerdict] = Field(default_factory=list)

    # True if every step scored acceptably -- i.e. nothing to diagnose
    pipeline_healthy: bool = True
