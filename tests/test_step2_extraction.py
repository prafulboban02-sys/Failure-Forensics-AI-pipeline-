import json
from src.pipeline.schemas import IntakeOutput
from src.pipeline import step2_extraction


def _intake(text="Invoice text", doc_id="doc1"):
    return IntakeOutput(
        doc_id=doc_id, raw_text=text, char_count=len(text), source_filename="f.txt"
    )


def test_extraction_happy_path(monkeypatch, fake_llm_factory):
    fake_response = json.dumps({
        "parties": ["Acme Corp"],
        "dates": ["2026-01-01"],
        "amounts": [100.0],
        "currency": "USD",
        "reference_numbers": ["REF-1"],
        "confidence": 0.95,
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step2_extraction, "get_llm", lambda temperature=0.0: fake_llm)

    result = step2_extraction.run_extraction(_intake())

    assert result.entities.parties == ["Acme Corp"]
    assert result.entities.amounts == [100.0]
    assert result.extraction_confidence == 0.95
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_extraction_handles_malformed_json_gracefully(monkeypatch, fake_llm_factory):
    """This is the core promise of the tool: a broken LLM response must
    become a diagnosable low-confidence result, never an uncaught crash."""
    fake_llm = fake_llm_factory("this is not json at all {{{")
    monkeypatch.setattr(step2_extraction, "get_llm", lambda temperature=0.0: fake_llm)

    result = step2_extraction.run_extraction(_intake())

    assert result.extraction_confidence == 0.0
    assert result.entities.parties == []
    assert result.raw_llm_response == "this is not json at all {{{"


def test_extraction_strips_markdown_code_fences(monkeypatch, fake_llm_factory):
    fake_response = "```json\n" + json.dumps({
        "parties": [], "dates": [], "amounts": [], "currency": "UNKNOWN",
        "reference_numbers": [], "confidence": 0.5,
    }) + "\n```"
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step2_extraction, "get_llm", lambda temperature=0.0: fake_llm)

    result = step2_extraction.run_extraction(_intake())

    assert result.extraction_confidence == 0.5


def test_extraction_missing_dates_is_preserved_not_hidden(monkeypatch, fake_llm_factory):
    """Empty dates[] must survive as empty, not get defaulted to something
    that looks confident. This is the missing_date_invoice.txt failure mode."""
    fake_response = json.dumps({
        "parties": ["X"], "dates": [], "amounts": [10.0], "currency": "USD",
        "reference_numbers": [], "confidence": 0.9,
    })
    fake_llm = fake_llm_factory(fake_response)
    monkeypatch.setattr(step2_extraction, "get_llm", lambda temperature=0.0: fake_llm)

    result = step2_extraction.run_extraction(_intake())

    assert result.entities.dates == []
