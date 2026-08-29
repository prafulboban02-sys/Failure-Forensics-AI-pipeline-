"""
Walks a trace step by step and figures out where things actually broke.

The logic is simple: judge each step, and whichever one is the FIRST to
score badly is the root cause. Anything that scores badly after that is
probably just downstream damage from the earlier problem, not a separate
issue - the judge is supposed to notice that and call it propagation_error
instead of piling on blame.
"""

from src.tracing.storage import query_spans, load_span
from src.rca.judge import judge_step
from src.rca.schemas import RootCauseReport, JudgeVerdict, FailureCategory

STEP_ORDER = ["intake", "extraction", "classification", "summarization"]
QUALITY_THRESHOLD = 3  # 3 and below counts as a real problem, not just a nitpick


def analyze_trace(trace_id: str) -> RootCauseReport:
    rows = query_spans(trace_id=trace_id)
    if not rows:
        raise ValueError(f"No spans found for trace_id={trace_id}")

    spans_by_step = {r["step_name"]: load_span(r["json_path"]) for r in rows}
    doc_id = rows[0]["doc_id"]
    source_filename = rows[0]["source_filename"]

    # Ground truth text: prefer extraction's recorded input, fall back to intake's output.
    if "extraction" in spans_by_step:
        source_text = spans_by_step["extraction"].input_data.get("raw_text", "")
    elif "intake" in spans_by_step:
        source_text = spans_by_step["intake"].output_data.get("raw_text", "")
    else:
        source_text = ""

    verdicts: list[JudgeVerdict] = []

    for step_name in STEP_ORDER:
        span = spans_by_step.get(step_name)
        if span is None:
            continue  # step never ran (pipeline stopped earlier)

        if step_name == "intake":
            # Deterministic, no LLM call -- judge trivially rather than
            # spending an LLM call on it.
            verdicts.append(JudgeVerdict(
                step_name="intake",
                quality_score=5 if span.status == "ok" else 1,
                category=FailureCategory.NONE,
                reasoning="Deterministic ingestion step; not LLM-judged.",
            ))
            continue

        if span.status == "error":
            verdicts.append(JudgeVerdict(
                step_name=step_name,
                quality_score=1,
                category=FailureCategory.NONE,
                reasoning=f"Step crashed before producing output: {span.error_message}",
                specific_issues=["step_crashed"],
            ))
            continue

        # A deterministic, code-checked finding (e.g. arithmetic that
        # provably doesn't add up) is not a matter of LLM opinion -- if
        # one exists, it wins outright, no judge call needed or wanted.
        verified_flags = span.output_data.get("verified_risk_flags") or []
        if verified_flags:
            verdicts.append(JudgeVerdict(
                step_name=step_name,
                quality_score=1,
                category=FailureCategory.VERIFIED_ERROR,
                reasoning="Deterministic check found a confirmed error: "
                          + "; ".join(verified_flags),
                specific_issues=verified_flags,
            ))
            continue

        verdict = judge_step(
            step_name=step_name,
            source_text=source_text,
            input_data=span.input_data,
            output_data=span.output_data,
        )
        verdicts.append(verdict)

    # Find the earliest step (in pipeline order) with an unacceptable score.
    root_cause_step = None
    root_cause_category = FailureCategory.NONE
    root_cause_explanation = ""
    pipeline_healthy = True

    for v in verdicts:
        if v.quality_score <= QUALITY_THRESHOLD:
            root_cause_step = v.step_name
            root_cause_category = v.category
            root_cause_explanation = v.reasoning
            pipeline_healthy = False
            break

    report = RootCauseReport(
        trace_id=trace_id,
        doc_id=doc_id,
        source_filename=source_filename,
        root_cause_step=root_cause_step,
        root_cause_category=root_cause_category,
        root_cause_explanation=root_cause_explanation,
        step_verdicts=verdicts,
        pipeline_healthy=pipeline_healthy,
    )
    return report
