"""
Quick verification tool: run the pipeline + root-cause analysis on ONE or
a few named documents (from data/batch_docs or data/sample_docs), without
re-running the full 50-document batch. Meant for exactly this workflow:
change a prompt, verify the fix on the specific document(s) that exposed
the gap, without waiting 15+ minutes for a full batch re-run.

Usage:
    python verify_fix.py math_error_total.txt contradictory_dates.txt
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.panel import Panel
from src.pipeline.chain import run_pipeline
from src.rca.analyzer import analyze_trace
from src.rca.storage import save_report

console = Console()
SEARCH_DIRS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "batch_docs"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample_docs"),
]


def find_doc(filename):
    for d in SEARCH_DIRS:
        path = os.path.join(d, filename)
        if os.path.exists(path):
            return path
    return None


def main():
    if len(sys.argv) < 2:
        console.print("Usage: python verify_fix.py <filename> [<filename> ...]")
        return

    for filename in sys.argv[1:]:
        path = find_doc(filename)
        if not path:
            console.print(f"[red]Could not find {filename} in data/batch_docs or data/sample_docs[/red]")
            continue

        with open(path) as f:
            raw_text = f.read()

        console.print(Panel(filename, style="cyan"))
        result = run_pipeline(raw_text, filename)
        report = analyze_trace(result.trace_id)
        save_report(report)

        if report.pipeline_healthy:
            console.print("[green]No issues found -- all steps scored acceptably.[/green]")
        else:
            console.print(f"[bold red]ROOT CAUSE: {report.root_cause_step}[/bold red] "
                           f"({report.root_cause_category.value})")
            console.print(report.root_cause_explanation)

        # Show the summarization output specifically -- that's what we changed.
        if result.summarization:
            console.print(f"\n  key_risk_flags (LLM): {result.summarization.key_risk_flags}")
            console.print(f"  verified_risk_flags (deterministic): {result.summarization.verified_risk_flags}")
        console.print()


if __name__ == "__main__":
    main()
