import json
from src.pipeline.schemas import IntakeOutput, ExtractionOutput, ExtractedEntities
from src.pipeline import step3_classification


def _intake():
    return IntakeOutput(
        doc_id="doc1", raw_text="some text", char_count=9, source_filename="f.txt"
    )


def _extraction():
    return ExtractionOutput(
        doc_id="doc1",
        entities=ExtractedEntities(),
        extraction_confidence=0.8,
        raw_llm_response="{}",
    )


def test_classification_happy_path(monkeypatch, fake_llm_factory):
    fake_response = json.dumps({
        "document_type": "invoice",
        "confidence": 0.95,
        "ambiguous": False,
        "candidate_types": [],
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step3_classification, "get_llm", lambda temperature=0.0: fake_llm)

    result = step3_classification.run_classification(_intake(), _extraction())

    assert result.document_type.value == "invoice"
    assert result.classification_confidence == 0.95
    assert result.ambiguous is False


def test_classification_detects_ambiguity_when_flagged(monkeypatch, fake_llm_factory):
    """Mirrors the real ambiguous_category_doc.txt case: a document that
    could plausibly be two types should come back ambiguous=True."""
    fake_response = json.dumps({
        "document_type": "contract",
        "confidence": 0.6,
        "ambiguous": True,
        "candidate_types": ["contract", "purchase_order"],
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step3_classification, "get_llm", lambda temperature=0.0: fake_llm)

    result = step3_classification.run_classification(_intake(), _extraction())

    assert result.ambiguous is True
    assert set(t.value for t in result.candidate_types) == {"contract", "purchase_order"}


def test_classification_malformed_response_falls_back_to_unknown(monkeypatch, fake_llm_factory):
    fake_llm = fake_llm_factory("garbage, not json")
    monkeypatch.setattr(step3_classification, "get_llm", lambda temperature=0.0: fake_llm)

    result = step3_classification.run_classification(_intake(), _extraction())

    assert result.document_type.value == "unknown"
    assert result.classification_confidence == 0.0
    assert result.ambiguous is True  # unknown classification should be treated as ambiguous
