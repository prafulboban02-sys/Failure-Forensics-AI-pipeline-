"""
Checks whether stated confidence, and the judge's verdict, are actually
trustworthy - not just whether they exist.

Two things get measured, using every run recorded so far:
1. Does the pipeline's own confidence score predict whether it got the
   answer right?
2. Does the judge's score agree with the known-correct answer?

Usage:
    python calibration_report.py
"""

import sys
import os
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.sample_docs.ground_truth import GROUND_TRUTH
from src.tracing.storage import get_connection, query_spans, load_span
from src.rca.storage import load_report_by_trace_id

console = Console()


def all_traces():
    """Returns [(trace_id, source_filename, timestamp), ...] for every
    pipeline run ever recorded, oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT trace_id, source_filename, MIN(timestamp) as ts "
            "FROM spans GROUP BY trace_id ORDER BY ts"
        ).fetchall()
        return rows


def main():
    traces = all_traces()
    if not traces:
        console.print("[yellow]No traces recorded yet. Run `python run_demo.py` first.[/yellow]")
        return

    table = Table(title="Calibration across every recorded run")
    for col in ["file", "trace", "relevant step", "stated conf",
                "ground truth", "judge score", "judge correct?"]:
        table.add_column(col)

    pipeline_miscalibrated = 0   # high confidence but actually wrong
    judge_miscalibrated = 0      # judge scored it fine but it was actually wrong (or vice versa)
    evaluable_count = 0

    for trace_id, filename, _ts in traces:
        if filename not in GROUND_TRUTH:
            continue

        relevant_step, _desc, check_fn = GROUND_TRUTH[filename]
        rows = query_spans(trace_id=trace_id)
        spans = {r["step_name"]: load_span(r["json_path"]) for r in rows}

        is_correct = check_fn(spans)
        if is_correct is None:
            continue  # relevant step didn't run this trace, skip

        evaluable_count += 1
        step_span = spans.get(relevant_step)
        stated_conf = step_span.confidence if step_span else None

        report = load_report_by_trace_id(trace_id)
        judge_score = None
        judge_says_ok = None
        if report:
            verdict = next((v for v in report.step_verdicts if v.step_name == relevant_step), None)
            if verdict:
                judge_score = verdict.quality_score
                judge_says_ok = judge_score >= 4

        # Pipeline miscalibration: stated confidence high (>=4) but actually wrong
        if stated_conf is not None and stated_conf >= 4 and not is_correct:
            pipeline_miscalibrated += 1

        # Judge miscalibration: judge's verdict disagrees with known ground truth
        judge_correct_str = "-"
        if judge_says_ok is not None:
            judge_agrees = (judge_says_ok == is_correct)
            judge_correct_str = "[green]yes[/green]" if judge_agrees else "[red]NO[/red]"
            if not judge_agrees:
                judge_miscalibrated += 1

        table.add_row(
            filename,
            trace_id[:8],
            relevant_step,
            f"{stated_conf}/5" if stated_conf is not None else "-",
            "[green]correct[/green]" if is_correct else "[red]WRONG[/red]",
            f"{judge_score}/5" if judge_score is not None else "(not analyzed)",
            judge_correct_str,
        )

    console.print(table)
    console.print()
    console.print(f"[bold]Evaluable runs: {evaluable_count}[/bold]")
    console.print(
        f"[bold]Pipeline miscalibration[/bold] (stated confidence >=4/5 but "
        f"actually wrong): {pipeline_miscalibrated}/{evaluable_count}"
    )
    console.print(
        f"[bold]Judge miscalibration[/bold] (judge's verdict disagreed with "
        f"known ground truth): {judge_miscalibrated}/{evaluable_count}"
    )
    console.print(
        "\n[dim]Run this again after collecting more runs -- with only a "
        "handful of samples per document these are directional, not "
        "statistically rigorous. At 50 documents (Phase 6) this becomes a "
        "real reliability signal.[/dim]"
    )


if __name__ == "__main__":
    main()
