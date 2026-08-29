"""
Phase 3 CLI.

Usage:
    python analyze_failures.py --trace <trace_id>   # analyze one trace
    python analyze_failures.py --all                # analyze every trace ever recorded
    python analyze_failures.py --unhealthy-only      # after --all, show just the reports
"""

import argparse
from rich.console import Console
from rich.panel import Panel
from src.tracing.storage import get_connection
from src.rca.analyzer import analyze_trace
from src.rca.storage import save_report, query_reports, load_report

console = Console()


def all_trace_ids() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT DISTINCT trace_id FROM spans").fetchall()
        return [r[0] for r in rows]


def print_report(report):
    color = "green" if report.pipeline_healthy else "red"
    header = f"{report.source_filename}  (trace {report.trace_id[:8]})"
    console.print(Panel(header, style=color))

    if report.pipeline_healthy:
        console.print("  [green]No issues found -- all steps scored acceptably.[/green]")
    else:
        console.print(f"  [bold red]ROOT CAUSE: {report.root_cause_step}[/bold red]")
        console.print(f"  Category: [yellow]{report.root_cause_category.value}[/yellow]")
        console.print(f"  Why: {report.root_cause_explanation}")

    console.print("\n  Step-by-step verdicts:")
    for v in report.step_verdicts:
        marker = "🔴" if v.quality_score <= 3 else "🟢"
        console.print(f"    {marker} {v.step_name}: {v.quality_score}/5 [{v.category.value}]")
        if v.specific_issues:
            console.print(f"        issues: {', '.join(v.specific_issues)}")
    console.print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--unhealthy-only", action="store_true")
    args = parser.parse_args()

    if args.trace:
        report = analyze_trace(args.trace)
        save_report(report)
        print_report(report)
        return

    if args.all:
        trace_ids = all_trace_ids()
        console.print(f"[cyan]Analyzing {len(trace_ids)} traces...[/cyan]\n")
        reports = []
        for tid in trace_ids:
            report = analyze_trace(tid)
            save_report(report)
            reports.append(report)

        for report in reports:
            if args.unhealthy_only and report.pipeline_healthy:
                continue
            print_report(report)

        unhealthy = sum(1 for r in reports if not r.pipeline_healthy)
        console.print(
            f"[bold]Summary: {unhealthy}/{len(reports)} traces flagged with a root cause.[/bold]"
        )
        return

    console.print("[yellow]Specify --trace <trace_id> or --all[/yellow]")


if __name__ == "__main__":
    main()
