from src.feedback.schemas import EvalCase, EvalRunResult
from src.feedback import storage as eval_storage


def _redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_storage, "CASES_DIR", str(tmp_path))
    monkeypatch.setattr(eval_storage, "DB_PATH", str(tmp_path / "idx.db"))


def _make_case(**overrides) -> EvalCase:
    defaults = dict(
        eval_id="gt::test.txt", source_filename="test.txt", relevant_step="extraction",
        failure_category="ground_truth_violation", description="test case",
        origin="ground_truth",
    )
    defaults.update(overrides)
    return EvalCase(**defaults)


def test_latest_status_none_with_no_history():
    case = _make_case()
    assert case.latest_status is None
    assert case.resolution_rate is None


def test_latest_status_reflects_most_recent_run():
    case = _make_case()
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=False))
    case.run_history.append(EvalRunResult(trace_id="t2", resolved=True))
    assert case.latest_status is True


def test_resolution_rate_computed_correctly():
    case = _make_case()
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=False))
    case.run_history.append(EvalRunResult(trace_id="t2", resolved=True))
    case.run_history.append(EvalRunResult(trace_id="t3", resolved=True))
    assert case.resolution_rate == 2 / 3


def test_resolution_rate_ignores_needs_review_entries():
    case = _make_case()
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=None))
    case.run_history.append(EvalRunResult(trace_id="t2", resolved=True))
    assert case.resolution_rate == 1.0


def test_save_eval_case_with_colons_in_id_works_on_windows(monkeypatch, tmp_path):
    """Regression test: eval_ids use '::' as a readable separator, which
    is an ILLEGAL filename character on Windows and crashed with
    OSError: [Errno 22] Invalid argument until this was sanitized."""
    _redirect(monkeypatch, tmp_path)
    case = _make_case(eval_id="gt::some_document.txt")
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=False))

    eval_storage.save_eval_case(case)  # must not raise

    loaded = eval_storage.load_eval_case_by_id("gt::some_document.txt")
    assert loaded is not None
    assert loaded.eval_id == "gt::some_document.txt"  # logical id preserved, only the filename was sanitized


def test_save_and_load_eval_case_roundtrip(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    case = _make_case()
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=False))
    eval_storage.save_eval_case(case)

    loaded = eval_storage.load_eval_case_by_id(case.eval_id)
    assert loaded is not None
    assert loaded.eval_id == case.eval_id
    assert len(loaded.run_history) == 1


def test_load_missing_eval_case_returns_none(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    assert eval_storage.load_eval_case_by_id("does::not::exist") is None


def test_list_eval_cases_reflects_latest_status(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    case = _make_case()
    case.run_history.append(EvalRunResult(trace_id="t1", resolved=False))
    eval_storage.save_eval_case(case)

    rows = eval_storage.list_eval_cases()
    assert len(rows) == 1
    assert rows[0]["latest_status"] == "still_failing"
