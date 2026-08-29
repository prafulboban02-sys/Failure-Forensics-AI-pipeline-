"""
The actual regression test. For every eval case with a known ground-truth
oracle, re-runs the ORIGINAL document through the pipeline fresh (a brand
new trace, fully instrumented as usual), re-checks it against ground
truth, and records whether the failure is still happening.

Manual-flag cases (real documents with no automatic oracle) are listed
separately for human review -- there's nothing to auto-verify them against.

Usage:
    python eval_runner.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from data.sample_docs.ground_truth import GROUND_TRUTH
from src.pipeline.chain import run_pipeline
from src.tracing.storage import query_spans, load_span
from src.feedback.storage import list_eval_cases, load_eval_case_by_id, save_eval_case
from src.feedback.schemas import EvalRunResult

console = Console()
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample_docs")


def sparkline(run_history) -> str:
    symbols = []
    for r in run_history[-10:]:  # last 10 runs
        if r.resolved is True:
            symbols.append("[green]✓[/green]")
        elif r.resolved is False:
            symbols.append("[red]✗[/red]")
        else:
            symbols.append("[dim]?[/dim]")
    return "".join(symbols)


def main():
    all_cases = list_eval_cases()
    if not all_cases:
        console.print(
            "[yellow]No eval cases yet. Run `python generate_eval_cases.py` first "
            "(after `python run_demo.py` and having some failing runs recorded).[/yellow]"
        )
        return

    ground_truth_cases = [c for c in all_cases if c["origin"] == "ground_truth"]
    manual_cases = [c for c in all_cases if c["origin"] == "manual_flag"]

    console.print(f"[cyan]Re-running {len(ground_truth_cases)} ground-truth eval case(s)...[/cyan]\n")

    table = Table(title="Regression results")
    for col in ["file", "step", "this run", "resolution rate", "recent history"]:
        table.add_column(col)

    for row in ground_truth_cases:
        filename = row["source_filename"]
        eval_id = row["eval_id"]
        case = load_eval_case_by_id(eval_id)
        if case is None or filename not in GROUND_TRUTH:
            continue

        relevant_step, _desc, check_fn = GROUND_TRUTH[filename]

        doc_path = os.path.join(SAMPLE_DIR, filename)
        if not os.path.exists(doc_path):
            console.print(f"[yellow]Skipping {filename}: sample file not found on disk.[/yellow]")
            continue
        with open(doc_path) as f:
            raw_text = f.read()

        # Fresh, fully-traced pipeline run -- this is a real regression test,
        # not a replay of old data.
        result = run_pipeline(raw_text, filename)
        span_rows = query_spans(trace_id=result.trace_id)
        spans = {r["step_name"]: load_span(r["json_path"]) for r in span_rows}
        is_correct_now = check_fn(spans)

        case.run_history.append(EvalRunResult(trace_id=result.trace_id, resolved=is_correct_now))
        save_eval_case(case)

        this_run = "—" if is_correct_now is None else ("[green]RESOLVED[/green]" if is_correct_now else "[red]still failing[/red]")
        rate = case.resolution_rate
        rate_str = f"{rate*100:.0f}%" if rate is not None else "—"

        table.add_row(filename, relevant_step, this_run, rate_str, sparkline(case.run_history))

    console.print(table)

    if manual_cases:
        console.print(f"\n[bold]{len(manual_cases)} manually-flagged case(s) need human review "
                       f"(no automatic oracle):[/bold]")
        for row in manual_cases:
            console.print(f"  - {row['source_filename']} / {row['relevant_step']}  (eval_id: {row['eval_id']})")


if __name__ == "__main__":
    main()
