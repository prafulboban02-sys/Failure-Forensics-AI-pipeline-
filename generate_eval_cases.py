"""
Scans every trace you've ever recorded. For any sample document with a
KNOWN correct answer (ground_truth.py) that actually failed on a given
run, creates or updates a durable EvalCase -- so that specific failure
mode is now tracked, not just noticed once and forgotten.

Usage:
    python generate_eval_cases.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from data.sample_docs.ground_truth import GROUND_TRUTH
from src.tracing.storage import get_connection, query_spans, load_span
from src.feedback.schemas import EvalCase, EvalRunResult
from src.feedback.storage import save_eval_case, load_eval_case_by_id

console = Console()


def all_traces():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trace_id, source_filename, MIN(timestamp) as ts "
            "FROM spans GROUP BY trace_id ORDER BY ts"
        ).fetchall()
    return rows


def main():
    traces = all_traces()
    created, updated = 0, 0

    for trace_id, filename, ts in traces:
        if filename not in GROUND_TRUTH:
            continue

        relevant_step, description, check_fn = GROUND_TRUTH[filename]
        rows = query_spans(trace_id=trace_id)
        spans = {r["step_name"]: load_span(r["json_path"]) for r in rows}

        is_correct = check_fn(spans)
        if is_correct is None:
            continue

        eval_id = f"gt::{filename}"
        existing = load_eval_case_by_id(eval_id)

        if is_correct is False:
            step_span = spans.get(relevant_step)
            if existing is None:
                case = EvalCase(
                    eval_id=eval_id,
                    source_filename=filename,
                    relevant_step=relevant_step,
                    failure_category="ground_truth_violation",
                    description=description,
                    original_input=step_span.input_data if step_span else {},
                    example_failing_output=step_span.output_data if step_span else {},
                    origin="ground_truth",
                    created_from_trace_id=trace_id,
                )
                created += 1
            else:
                case = existing
                # refresh the example to the most recent failing instance
                case.example_failing_output = step_span.output_data if step_span else {}
                updated += 1

            case.run_history.append(EvalRunResult(trace_id=trace_id, resolved=False))
            save_eval_case(case)

        else:  # is_correct is True
            if existing is not None:
                # This failure mode has been seen before -- record that
                # THIS run resolved it, so resolution rate reflects reality.
                existing.run_history.append(EvalRunResult(trace_id=trace_id, resolved=True))
                save_eval_case(existing)
                updated += 1

    console.print(f"[green]Eval cases created: {created}[/green]")
    console.print(f"[cyan]Eval cases updated: {updated}[/cyan]")
    console.print("\nRun `python eval_runner.py` to actively re-test these against fresh pipeline runs.")


if __name__ == "__main__":
    main()
