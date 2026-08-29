"""
Phase 5: feedback loop. A confirmed failure becomes a durable EvalCase --
a record of "this input, on this step, produced this wrong output" that
gets RE-CHECKED every time you re-run the eval suite, so you can actually
answer "did my prompt fix work?" instead of eyeballing one new run.

Two ways a case gets created:
  - origin="ground_truth": automatically, when a sample document with a
    KNOWN correct answer (data/sample_docs/ground_truth.py) fails.
  - origin="manual_flag": a human clicks "flag this" in the dashboard on
    a real document with no automatic oracle -- there's no ground truth
    function to re-check it against, so it's tracked for review rather
    than auto pass/fail.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class EvalRunResult(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str
    resolved: Optional[bool]  # True=no longer fails, False=still fails, None=no oracle, needs human review
    notes: str = ""


class EvalCase(BaseModel):
    eval_id: str
    source_filename: str
    relevant_step: str
    failure_category: str
    description: str

    original_input: dict = Field(default_factory=dict)
    example_failing_output: dict = Field(default_factory=dict)
    corrected_note: Optional[str] = None  # freeform human note on what SHOULD happen

    origin: str  # "ground_truth" | "manual_flag"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_from_trace_id: str = ""

    run_history: list[EvalRunResult] = Field(default_factory=list)

    @property
    def latest_status(self) -> Optional[bool]:
        if not self.run_history:
            return None
        return self.run_history[-1].resolved

    @property
    def resolution_rate(self) -> Optional[float]:
        decisive = [r for r in self.run_history if r.resolved is not None]
        if not decisive:
            return None
        return sum(1 for r in decisive if r.resolved) / len(decisive)
