import json
from src.pipeline import step2_extraction, step3_classification, step4_summarization
from src.pipeline import chain
from src.tracing import storage


def _patch_all_llms(monkeypatch, fake_llm_factory, extraction_json, classification_json, summarization_json):
    monkeypatch.setattr(step2_extraction, "get_llm", lambda temperature=0.0: fake_llm_factory(extraction_json))
    monkeypatch.setattr(step3_classification, "get_llm", lambda temperature=0.0: fake_llm_factory(classification_json))
    monkeypatch.setattr(step4_summarization, "get_llm", lambda temperature=0.2: fake_llm_factory(summarization_json))


def _redirect_traces(monkeypatch, tmp_path):
    """Point the tracer/storage at a scratch directory so tests never touch
    (or get polluted by) the real traces/ folder."""
    monkeypatch.setattr(storage, "TRACES_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "test_index.db"))


def test_full_pipeline_happy_path(monkeypatch, fake_llm_factory, tmp_path):
    _redirect_traces(monkeypatch, tmp_path)
    _patch_all_llms(
        monkeypatch, fake_llm_factory,
        extraction_json=json.dumps({
            "parties": ["Acme"], "dates": ["2026-01-01"], "amounts": [50.0],
            "currency": "USD", "reference_numbers": ["R1"], "confidence": 0.9,
        }),
        classification_json=json.dumps({
            "document_type": "invoice", "confidence": 0.95,
            "ambiguous": False, "candidate_types": [],
        }),
        summarization_json=json.dumps({
            "summary": "An invoice.", "key_risk_flags": [], "self_confidence": 5,
        }),
    )

    result = chain.run_pipeline("Some invoice text", "test.txt")

    assert result.failed_at_step is None
    assert result.extraction.entities.parties == ["Acme"]
    assert result.classification.document_type.value == "invoice"
    assert result.summarization.self_confidence == 5
    assert result.trace_id is not None

    # 4 spans (intake, extraction, classification, summarization) should
    # have been persisted for this one run.
    rows = storage.query_spans(trace_id=result.trace_id)
    assert len(rows) == 4
    assert {r["step_name"] for r in rows} == {
        "intake", "extraction", "classification", "summarization"
    }
    assert all(r["status"] == "ok" for r in rows)


def test_pipeline_stops_at_extraction_failure_and_still_traces_it(
    monkeypatch, fake_llm_factory, tmp_path
):
    """If extraction raises, classification/summarization must never run,
    AND the failure must still be captured as a span with status=error."""
    _redirect_traces(monkeypatch, tmp_path)

    def broken_llm(temperature=0.0):
        class Broken:
            def invoke(self, messages):
                raise RuntimeError("simulated LLM outage")
        return Broken()

    monkeypatch.setattr(step2_extraction, "get_llm", broken_llm)

    result = chain.run_pipeline("Some text", "test.txt")

    assert result.failed_at_step == "extraction"
    assert result.classification is None
    assert result.summarization is None

    rows = storage.query_spans(trace_id=result.trace_id)
    step_names = {r["step_name"] for r in rows}
    assert "intake" in step_names
    assert "extraction" in step_names
    assert "classification" not in step_names  # never ran, never traced

    extraction_row = [r for r in rows if r["step_name"] == "extraction"][0]
    assert extraction_row["status"] == "error"


def test_confidence_is_normalized_to_1_5_scale_across_steps(
    monkeypatch, fake_llm_factory, tmp_path
):
    _redirect_traces(monkeypatch, tmp_path)
    _patch_all_llms(
        monkeypatch, fake_llm_factory,
        extraction_json=json.dumps({
            "parties": [], "dates": [], "amounts": [], "currency": "UNKNOWN",
            "reference_numbers": [], "confidence": 0.2,
        }),
        classification_json=json.dumps({
            "document_type": "unknown", "confidence": 0.2,
            "ambiguous": True, "candidate_types": [],
        }),
        summarization_json=json.dumps({
            "summary": "x", "key_risk_flags": [], "self_confidence": 1,
        }),
    )

    result = chain.run_pipeline("text", "test.txt")
    rows = storage.query_spans(trace_id=result.trace_id)

    for r in rows:
        assert 1 <= r["confidence"] <= 5
