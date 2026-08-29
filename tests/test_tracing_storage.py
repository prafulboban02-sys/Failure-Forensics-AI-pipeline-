from src.tracing import storage
from src.tracing.schemas import Span


def _redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "TRACES_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "idx.db"))


def _make_span(**overrides) -> Span:
    defaults = dict(
        span_id="s1", trace_id="t1", doc_id="d1", step_name="extraction",
        source_filename="f.txt", status="ok", confidence=4, latency_ms=123.4,
        input_tokens=10, output_tokens=20,
    )
    defaults.update(overrides)
    return Span(**defaults)


def test_save_and_load_span_roundtrip(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    span = _make_span()
    json_path = storage.save_span(span)

    loaded = storage.load_span(json_path)
    assert loaded.span_id == span.span_id
    assert loaded.confidence == 4
    assert loaded.status == "ok"


def test_query_spans_filters_by_status(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    storage.save_span(_make_span(span_id="ok1", status="ok"))
    storage.save_span(_make_span(span_id="err1", status="error", error_message="boom"))

    errors = storage.query_spans(status="error")
    assert len(errors) == 1
    assert errors[0]["span_id"] == "err1"


def test_query_spans_filters_by_confidence(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    storage.save_span(_make_span(span_id="low", confidence=1))
    storage.save_span(_make_span(span_id="high", confidence=5))

    low_conf = storage.query_spans(max_confidence=2)
    assert len(low_conf) == 1
    assert low_conf[0]["span_id"] == "low"


def test_query_spans_filters_by_trace_id(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    storage.save_span(_make_span(span_id="a", trace_id="trace-A"))
    storage.save_span(_make_span(span_id="b", trace_id="trace-B"))

    rows = storage.query_spans(trace_id="trace-A")
    assert len(rows) == 1
    assert rows[0]["span_id"] == "a"
