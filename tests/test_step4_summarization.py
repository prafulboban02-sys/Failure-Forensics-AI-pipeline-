import json
from src.pipeline.schemas import (
    IntakeOutput, ExtractionOutput, ExtractedEntities, ClassificationOutput,
)
from src.pipeline import step4_summarization


def _intake():
    return IntakeOutput(
        doc_id="doc1", raw_text="some text", char_count=9, source_filename="f.txt"
    )


def _extraction():
    return ExtractionOutput(
        doc_id="doc1", entities=ExtractedEntities(),
        extraction_confidence=0.8, raw_llm_response="{}",
    )


def _classification():
    return ClassificationOutput(
        doc_id="doc1", document_type="invoice", classification_confidence=0.9,
    )


def test_summarization_happy_path(monkeypatch, fake_llm_factory):
    fake_response = json.dumps({
        "summary": "An invoice for $100.",
        "key_risk_flags": [],
        "self_confidence": 5,
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step4_summarization, "get_llm", lambda temperature=0.2: fake_llm)

    result = step4_summarization.run_summarization(_intake(), _extraction(), _classification())

    assert result.summary == "An invoice for $100."
    assert result.self_confidence == 5


def test_summarization_confidence_is_clamped_to_1_5(monkeypatch, fake_llm_factory):
    """A model returning an out-of-range self-rating (e.g. 8, or 0) should
    never corrupt the confidence scale the rest of the tool relies on."""
    fake_response = json.dumps({
        "summary": "x", "key_risk_flags": [], "self_confidence": 8,
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step4_summarization, "get_llm", lambda temperature=0.2: fake_llm)

    result = step4_summarization.run_summarization(_intake(), _extraction(), _classification())

    assert result.self_confidence == 5  # clamped down from 8


def test_summarization_malformed_json_yields_low_confidence(monkeypatch, fake_llm_factory):
    fake_llm = fake_llm_factory("not json")
    monkeypatch.setattr(step4_summarization, "get_llm", lambda temperature=0.2: fake_llm)

    result = step4_summarization.run_summarization(_intake(), _extraction(), _classification())

    assert result.self_confidence == 1
    assert "summarization_parse_failure" in result.key_risk_flags
