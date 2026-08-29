"""
Phase 1 demo: run every sample document through the full pipeline and print
a readable report of what each step produced (or where it broke).

Usage:
    python run_demo.py
"""

import os
import glob
from rich.console import Console
from rich.panel import Panel
from src.pipeline.chain import run_pipeline

console = Console()

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "data", "sample_docs")


def main():
    files = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.txt")))
    if not files:
        console.print(
            "[yellow]No sample docs found. Run "
            "`python data/sample_docs/generate_samples.py` first.[/yellow]"
        )
        return

    for filepath in files:
        filename = os.path.basename(filepath)
        with open(filepath) as f:
            raw_text = f.read()

        console.print(Panel(f"[bold]{filename}[/bold]", style="cyan"))
        result = run_pipeline(raw_text, filename)

        console.print(f"  doc_id: {result.doc_id}  |  trace_id: {result.trace_id}")

        if result.failed_at_step:
            console.print(
                f"  [red]FAILED at step: {result.failed_at_step}[/red] "
                f"-> {result.error_message}"
            )
            continue

        console.print(
            f"  extraction_confidence: {result.extraction.extraction_confidence:.2f}"
        )
        console.print(f"  entities: {result.extraction.entities.model_dump()}")
        console.print(
            f"  classification: {result.classification.document_type.value} "
            f"(confidence {result.classification.classification_confidence:.2f}, "
            f"ambiguous={result.classification.ambiguous})"
        )
        console.print(f"  summary: {result.summarization.summary}")
        console.print(f"  risk_flags (LLM): {result.summarization.key_risk_flags}")
        console.print(f"  risk_flags (verified/deterministic): {result.summarization.verified_risk_flags}")
        console.print()


if __name__ == "__main__":
    main()
