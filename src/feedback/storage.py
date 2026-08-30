"""
Same pattern as tracing/storage.py and rca/storage.py: full case as JSON,
lightweight SQLite index on top for querying.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from src.feedback.schemas import EvalCase

CASES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "eval_cases")
DB_PATH = os.path.join(CASES_DIR, "eval_index.db")

os.makedirs(CASES_DIR, exist_ok=True)


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_cases (
            eval_id TEXT PRIMARY KEY,
            source_filename TEXT NOT NULL,
            relevant_step TEXT NOT NULL,
            failure_category TEXT NOT NULL,
            origin TEXT NOT NULL,
            created_at TEXT NOT NULL,
            latest_status TEXT,
            run_count INTEGER NOT NULL,
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


def _safe_filename(eval_id: str) -> str:
    """Windows forbids : \\ / * ? " < > | in filenames. eval_ids use '::'
    as a readable separator, which broke real Windows testing -- sanitize
    here rather than relying on every caller to avoid unsafe characters."""
    return re.sub(r'[\\/*?:"<>|]', "_", eval_id)


def save_eval_case(case: EvalCase) -> str:
    json_path = os.path.join(CASES_DIR, f"{_safe_filename(case.eval_id)}.json")
    with open(json_path, "w") as f:
        f.write(case.model_dump_json(indent=2))

    latest = case.latest_status
    latest_str = "unknown" if latest is None else ("resolved" if latest else "still_failing")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO eval_cases
                (eval_id, source_filename, relevant_step, failure_category,
                 origin, created_at, latest_status, run_count, json_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case.eval_id, case.source_filename, case.relevant_step,
                case.failure_category, case.origin, case.created_at,
                latest_str, len(case.run_history), json_path,
            ),
        )
        conn.commit()
    return json_path


def load_eval_case(json_path: str) -> EvalCase:
    filename = json_path.replace("\\", "/").rsplit("/", 1)[-1]
    real_path = os.path.join(CASES_DIR, filename)
    with open(real_path) as f:
        return EvalCase.model_validate_json(f.read())


def load_eval_case_by_id(eval_id: str) -> EvalCase | None:
    json_path = os.path.join(CASES_DIR, f"{_safe_filename(eval_id)}.json")
    if not os.path.exists(json_path):
        return None
    return load_eval_case(json_path)


def list_eval_cases() -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM eval_cases ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]