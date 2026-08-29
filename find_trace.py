"""
Utility: the demo/analyze output only shows a truncated trace_id (first 8
chars). Use this to find the FULL trace_id for a document, so you can pass
it to `inspect_traces.py --trace <full_id>` or `analyze_failures.py --trace <full_id>`.

Usage:
    python find_trace.py ambiguous_category
"""

import sys
from src.tracing.storage import get_connection


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_trace.py <filename substring>")
        return

    needle = sys.argv[1]
    with get_connection() as conn:
        conn.row_factory = None
        rows = conn.execute(
            "SELECT DISTINCT trace_id, source_filename, timestamp FROM spans "
            "WHERE source_filename LIKE ? ORDER BY timestamp DESC",
            (f"%{needle}%",),
        ).fetchall()

    if not rows:
        print(f"No traces found matching '{needle}'")
        return

    for trace_id, filename, timestamp in rows:
        print(f"{trace_id}  |  {filename}  |  {timestamp}")


if __name__ == "__main__":
    main()
