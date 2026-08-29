"""
Phase 6: process all 50 batch documents end-to-end and produce the demo
summary -- "bad output in, trace explorer open, root cause diagnosed in
seconds."

Usage:
    python process_batch.py
"""

import sys
import os
import time
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.progress import track
from src.pipeline.chain import run_pipeline
from src.rca.analyzer import analyze_trace
from src.rca.storage import save_report

console = Console()
BATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "batch_docs")


def main():
    files = sorted(glob.glob(os.path.join(BATCH_DIR, "*.txt")))
    if not files:
        console.print(
            "[yellow]No batch documents found. Run "
            "`python data/batch_docs/generate_batch_docs.py` first.[/yellow]"
        )
        return

    console.print(f"[cyan]Processing {len(files)} documents through the full pipeline...[/cyan]")
    pipeline_start = time.perf_counter()

    results = []
    for filepath in track(files, description="Running pipeline..."):
        filename = os.path.basename(filepath)
        with open(filepath) as f:
            raw_text = f.read()
        result = run_pipeline(raw_text, filename)
        results.append((filename, result))

    pipeline_elapsed = time.perf_counter() - pipeline_start

    console.print(f"\n[cyan]Running root-cause analysis on all {len(results)} traces...[/cyan]")
    rca_start = time.perf_counter()

    reports = []
    for filename, result in track(results, description="Diagnosing..."):
        report = analyze_trace(result.trace_id)
        save_report(report)
        reports.append((filename, report))

    rca_elapsed = time.perf_counter() - rca_start
    total_elapsed = pipeline_elapsed + rca_elapsed

    # --- Summary ---
    flagged = [(f, r) for f, r in reports if not r.pipeline_healthy]
    healthy = [(f, r) for f, r in reports if r.pipeline_healthy]
    category_counts = {}
    for _f, r in flagged:
        cat = r.root_cause_category.value
        category_counts[cat] = category_counts.get(cat, 0) + 1

    table = Table(title=f"Batch run: {len(results)} documents")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Documents processed", str(len(results)))
    table.add_row("Flagged with a root cause", f"{len(flagged)} ({len(flagged)/len(results)*100:.0f}%)")
    table.add_row("Healthy", str(len(healthy)))
    table.add_row("Pipeline processing time", f"{pipeline_elapsed:.1f}s")
    table.add_row("Root-cause analysis time", f"{rca_elapsed:.1f}s")
    table.add_row("Total time (pipeline + diagnosis)", f"{total_elapsed:.1f}s")
    table.add_row("Avg time to diagnose PER document", f"{rca_elapsed/len(results):.1f}s")
    console.print(table)

    if category_counts:
        cat_table = Table(title="Failure categories found")
        cat_table.add_column("Category")
        cat_table.add_column("Count")
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    console.print("\n[bold]Flagged documents:[/bold]")
    for filename, report in flagged:
        console.print(
            f"  🔴 {filename}  ->  {report.root_cause_step} "
            f"({report.root_cause_category.value})"
        )

    console.print(
        f"\n[bold green]Summary line for your CV/demo:[/bold green] "
        f"processed {len(results)} documents and automatically diagnosed "
        f"{len(flagged)} real failures across {len(category_counts)} distinct "
        f"categories in {total_elapsed:.0f} seconds total "
        f"({rca_elapsed/len(results):.1f}s average per document to root-cause)."
    )


if __name__ == "__main__":
    main()
