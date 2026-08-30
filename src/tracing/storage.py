"""
Storage strategy: full span content lives in a JSON file per span (easy to
open, diff, or feed to an LLM-as-judge in Phase 3). SQLite holds a lightweight
index over those files so we can query "all failed spans", "all spans for
this trace", "all spans below confidence 3", etc. without loading every
JSON file into memory.
"""

import os
import json
import sqlite3
from contextlib import contextmanager
from src.tracing.schemas import Span

TRACES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "traces")
DB_PATH = os.path.join(TRACES_DIR, "traces_index.db")

os.makedirs(TRACES_DIR, exist_ok=True)


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spans (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence INTEGER,
            latency_ms REAL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            error_message TEXT,
            timestamp TEXT NOT NULL,
            json_path TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_id ON spans(trace_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON spans(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_id ON spans(doc_id)")
    conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def save_span(span: Span) -> str:
    """Writes the full span to a JSON file and indexes it in SQLite."""
    json_filename = f"{span.trace_id}__{span.step_name}.json"
    json_path = os.path.join(TRACES_DIR, json_filename)

    with open(json_path, "w") as f:
        f.write(span.model_dump_json(indent=2))

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO spans
                (span_id, trace_id, doc_id, step_name, source_filename,
                 status, confidence, latency_ms, input_tokens, output_tokens,
                 error_message, timestamp, json_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                span.span_id, span.trace_id, span.doc_id, span.step_name,
                span.source_filename, span.status, span.confidence,
                span.latency_ms, span.input_tokens, span.output_tokens,
                span.error_message, span.timestamp, json_path,
            ),
        )
        conn.commit()

    return json_path


def load_span(json_path: str) -> Span:
    # json_path in the index may be a stale absolute path baked in on a
    # different machine (e.g. committed from Windows, read back on a
    # Linux deploy). Re-anchor to wherever TRACES_DIR actually is now.
    # Windows paths use backslashes, which os.path.basename() on Linux
    # won't recognize as separators -- normalize both slash styles first.
    filename = json_path.replace("\\", "/").rsplit("/", 1)[-1]
    real_path = os.path.join(TRACES_DIR, filename)
    with open(real_path) as f:
        return Span.model_validate_json(f.read())


def query_spans(
    status: str | None = None,
    max_confidence: int | None = None,
    trace_id: str | None = None,
) -> list[dict]:
    """Returns index rows (not full spans) matching filters — used by the
    Phase 3 analyzer to find flagged traces before loading full JSON."""
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if max_confidence is not None:
        clauses.append("confidence <= ?")
        params.append(max_confidence)
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM spans {where} ORDER BY timestamp", params).fetchall()
        return [dict(r) for r in rows]