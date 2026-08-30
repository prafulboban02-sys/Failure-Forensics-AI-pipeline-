"""
Same pattern as src/tracing/storage.py: full report as JSON, lightweight
SQLite index on top for querying ("show me every propagation_error",
"show me every trace with an unhealthy pipeline").
"""

import os
import sqlite3
from contextlib import contextmanager
from src.rca.schemas import RootCauseReport

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "rca_reports")
DB_PATH = os.path.join(REPORTS_DIR, "rca_index.db")

os.makedirs(REPORTS_DIR, exist_ok=True)


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rca_reports (
            trace_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            root_cause_step TEXT,
            root_cause_category TEXT NOT NULL,
            pipeline_healthy INTEGER NOT NULL,
            json_path TEXT NOT NULL
        )
    """)
    conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def save_report(report: RootCauseReport) -> str:
    json_path = os.path.join(REPORTS_DIR, f"{report.trace_id}.json")
    with open(json_path, "w") as f:
        f.write(report.model_dump_json(indent=2))

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO rca_reports
                (trace_id, doc_id, source_filename, root_cause_step,
                 root_cause_category, pipeline_healthy, json_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.trace_id, report.doc_id, report.source_filename,
                report.root_cause_step, report.root_cause_category.value,
                int(report.pipeline_healthy), json_path,
            ),
        )
        conn.commit()
    return json_path


def load_report_by_trace_id(trace_id: str) -> RootCauseReport | None:
    json_path = os.path.join(REPORTS_DIR, f"{trace_id}.json")
    if not os.path.exists(json_path):
        return None
    return load_report(json_path)


def load_report(json_path: str) -> RootCauseReport:
    filename = json_path.replace("\\", "/").rsplit("/", 1)[-1]
    real_path = os.path.join(REPORTS_DIR, filename)
    with open(real_path) as f:
        return RootCauseReport.model_validate_json(f.read())


def query_reports(unhealthy_only: bool = False, category: str | None = None) -> list[dict]:
    clauses, params = [], []
    if unhealthy_only:
        clauses.append("pipeline_healthy = 0")
    if category:
        clauses.append("root_cause_category = ?")
        params.append(category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM rca_reports {where}", params).fetchall()
        return [dict(r) for r in rows]