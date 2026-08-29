from src.tracing import storage
from src.tracing.schemas import Span
from src.rca import analyzer
from src.rca.schemas import JudgeVerdict, FailureCategory


def _redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "TRACES_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "idx.db"))


def _seed_trace(trace_id, doc_id="d1", filename="f.txt"):
    """Writes a minimal 4-span trace directly to storage, bypassing the
    real pipeline -- we only want to test the analyzer's own logic here."""
    storage.save_span(Span(
        span_id="s0", trace_id=trace_id, doc_id=doc_id, step_name="intake",
        source_filename=filename, status="ok",
        output_data={"raw_text": "original document text"},
    ))
    storage.save_span(Span(
        span_id="s1", trace_id=trace_id, doc_id=doc_id, step_name="extraction",
        source_filename=filename, status="ok",
        input_data={"raw_text": "original document text"},
        output_data={"entities": {}},
    ))
    storage.save_span(Span(
        span_id="s2", trace_id=trace_id, doc_id=doc_id, step_name="classification",
        source_filename=filename, status="ok",
        input_data={"raw_text": "original document text"},
        output_data={"document_type": "invoice"},
    ))
    storage.save_span(Span(
        span_id="s3", trace_id=trace_id, doc_id=doc_id, step_name="summarization",
        source_filename=filename, status="ok",
        input_data={"raw_text": "original document text"},
        output_data={"summary": "x"},
    ))


def test_analyzer_picks_earliest_failing_step(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    _seed_trace("trace1")

    def fake_judge(step_name, source_text, input_data, output_data):
        # extraction is fine, classification is bad, summarization is also
        # bad (as a real pipeline would cascade) -- root cause should be
        # classification, not summarization.
        scores = {"extraction": 5, "classification": 2, "summarization": 2}
        categories = {
            "extraction": FailureCategory.NONE,
            "classification": FailureCategory.MISCLASSIFICATION,
            "summarization": FailureCategory.PROPAGATION_ERROR,
        }
        return JudgeVerdict(
            step_name=step_name,
            quality_score=scores[step_name],
            category=categories[step_name],
            reasoning=f"mock reasoning for {step_name}",
        )

    monkeypatch.setattr(analyzer, "judge_step", fake_judge)

    report = analyzer.analyze_trace("trace1")

    assert report.pipeline_healthy is False
    assert report.root_cause_step == "classification"
    assert report.root_cause_category == FailureCategory.MISCLASSIFICATION
    assert len(report.step_verdicts) == 4  # intake + 3 judged steps


def test_analyzer_reports_healthy_when_all_scores_good(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    _seed_trace("trace2")

    def fake_judge(step_name, source_text, input_data, output_data):
        return JudgeVerdict(
            step_name=step_name, quality_score=5,
            category=FailureCategory.NONE, reasoning="fine",
        )

    monkeypatch.setattr(analyzer, "judge_step", fake_judge)

    report = analyzer.analyze_trace("trace2")

    assert report.pipeline_healthy is True
    assert report.root_cause_step is None


def test_verified_risk_flags_override_judge_without_calling_it(monkeypatch, tmp_path):
    """A deterministic, code-checked finding must win outright -- and the
    judge must not even be consulted for that step, since there's nothing
    to adjudicate: the arithmetic either matches or it doesn't."""
    _redirect(monkeypatch, tmp_path)
    trace_id = "trace4"
    storage.save_span(Span(
        span_id="s0", trace_id=trace_id, doc_id="d1", step_name="intake",
        source_filename="f.txt", status="ok",
        output_data={"raw_text": "text"},
    ))
    storage.save_span(Span(
        span_id="s1", trace_id=trace_id, doc_id="d1", step_name="extraction",
        source_filename="f.txt", status="ok",
        input_data={"raw_text": "text"},
        output_data={"entities": {}},
    ))
    storage.save_span(Span(
        span_id="s2", trace_id=trace_id, doc_id="d1", step_name="classification",
        source_filename="f.txt", status="ok",
        input_data={"raw_text": "text"},
        output_data={"document_type": "invoice"},
    ))
    storage.save_span(Span(
        span_id="s3", trace_id=trace_id, doc_id="d1", step_name="summarization",
        source_filename="f.txt", status="ok",
        input_data={"raw_text": "text"},
        output_data={
            "summary": "looks fine",
            "key_risk_flags": [],  # the LLM itself saw nothing wrong
            "verified_risk_flags": ["Arithmetic mismatch on 'x': 2.0 x 3.0 = 6.00, but stated total is 99.00"],
        },
    ))

    def fake_judge_should_not_be_called_for_summarization(step_name, source_text, input_data, output_data):
        if step_name == "summarization":
            raise AssertionError("judge should be bypassed when verified_risk_flags is non-empty")
        return JudgeVerdict(step_name=step_name, quality_score=5, category=FailureCategory.NONE, reasoning="fine")

    monkeypatch.setattr(analyzer, "judge_step", fake_judge_should_not_be_called_for_summarization)

    report = analyzer.analyze_trace(trace_id)

    assert report.pipeline_healthy is False
    assert report.root_cause_step == "summarization"
    assert report.root_cause_category == FailureCategory.VERIFIED_ERROR
    assert "Arithmetic mismatch" in report.root_cause_explanation


def test_analyzer_treats_crashed_step_as_automatic_root_cause(monkeypatch, tmp_path):
    _redirect(monkeypatch, tmp_path)
    trace_id = "trace3"
    storage.save_span(Span(
        span_id="s0", trace_id=trace_id, doc_id="d1", step_name="intake",
        source_filename="f.txt", status="ok",
        output_data={"raw_text": "text"},
    ))
    storage.save_span(Span(
        span_id="s1", trace_id=trace_id, doc_id="d1", step_name="extraction",
        source_filename="f.txt", status="error",
        error_message="simulated crash",
    ))

    def fake_judge(*args, **kwargs):
        raise AssertionError("judge should never be called on a crashed step")

    monkeypatch.setattr(analyzer, "judge_step", fake_judge)

    report = analyzer.analyze_trace(trace_id)

    assert report.root_cause_step == "extraction"
    assert report.pipeline_healthy is False
