"""
Quick CLI to inspect what Phase 2 tracing actually captured, without
opening SQLite or JSON files by hand.

Usage:
    python inspect_traces.py                    # summary of all spans
    python inspect_traces.py --errors           # only failed spans
    python inspect_traces.py --low-confidence   # confidence <= 2
    python inspect_traces.py --trace <trace_id> # every span in one run
"""

import argparse
from rich.console import Console
from rich.table import Table
from src.tracing.storage import query_spans, load_span

console = Console()


def print_rows(rows: list[dict]):
    if not rows:
        console.print("[yellow]No matching spans found.[/yellow]")
        return
    table = Table(show_lines=False)
    for col in ["trace_id", "step_name", "status", "confidence", "latency_ms",
                "input_tokens", "output_tokens", "source_filename"]:
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["trace_id"][:8],
            r["step_name"],
            "[red]error[/red]" if r["status"] == "error" else "[green]ok[/green]",
            str(r["confidence"]),
            f'{r["latency_ms"]:.0f}ms' if r["latency_ms"] else "-",
            str(r["input_tokens"] or "-"),
            str(r["output_tokens"] or "-"),
            r["source_filename"],
        )
    console.print(table)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--errors", action="store_true")
    parser.add_argument("--low-confidence", action="store_true")
    parser.add_argument("--trace", type=str, default=None)
    args = parser.parse_args()

    status = "error" if args.errors else None
    max_confidence = 2 if args.low_confidence else None

    rows = query_spans(status=status, max_confidence=max_confidence, trace_id=args.trace)
    print_rows(rows)

    if args.trace and rows:
        console.print("\n[bold]Full span detail:[/bold]")
        for r in rows:
            span = load_span(r["json_path"])
            console.print(f"\n--- {span.step_name} ---")
            console.print(span.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
