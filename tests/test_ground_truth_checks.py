from src.tracing.schemas import Span
from data.sample_docs.ground_truth import GROUND_TRUTH


def _span(step_name, output_data, input_data=None):
    return Span(
        span_id="s", trace_id="t", doc_id="d", step_name=step_name,
        source_filename="f.txt", status="ok",
        input_data=input_data or {}, output_data=output_data,
    )


def test_ambiguous_check_true_when_flagged():
    _, _, check = GROUND_TRUTH["ambiguous_category_doc.txt"]
    spans = {"classification": _span("classification", {"ambiguous": True})}
    assert check(spans) is True


def test_ambiguous_check_false_when_not_flagged():
    _, _, check = GROUND_TRUTH["ambiguous_category_doc.txt"]
    spans = {"classification": _span("classification", {"ambiguous": False})}
    assert check(spans) is False


def test_ambiguous_check_none_when_step_missing():
    _, _, check = GROUND_TRUTH["ambiguous_category_doc.txt"]
    assert check({}) is None


def test_missing_date_check_true_on_empty_list():
    _, _, check = GROUND_TRUTH["missing_date_invoice.txt"]
    spans = {"extraction": _span("extraction", {"entities": {"dates": []}})}
    assert check(spans) is True


def test_missing_date_check_false_when_date_invented():
    _, _, check = GROUND_TRUTH["missing_date_invoice.txt"]
    spans = {"extraction": _span("extraction", {"entities": {"dates": ["2026-01-01"]}})}
    assert check(spans) is False


def test_currency_mismatch_check_true_when_flagged():
    _, _, check = GROUND_TRUTH["currency_mismatch_receipt.txt"]
    spans = {"summarization": _span("summarization", {
        "key_risk_flags": ["Currency mismatch: EUR symbol vs USD in words"]
    })}
    assert check(spans) is True


def test_currency_mismatch_check_false_when_not_flagged():
    _, _, check = GROUND_TRUTH["currency_mismatch_receipt.txt"]
    spans = {"summarization": _span("summarization", {"key_risk_flags": []})}
    assert check(spans) is False


def test_garbled_doc_check_true_on_low_confidence():
    _, _, check = GROUND_TRUTH["garbled_scan_artifact.txt"]
    spans = {"extraction": _span("extraction", {
        "extraction_confidence": 0.3, "entities": {"parties": ["a"]}
    })}
    assert check(spans) is True


def test_garbled_doc_check_true_when_missing_flagged_even_if_high_confidence():
    _, _, check = GROUND_TRUTH["garbled_scan_artifact.txt"]
    spans = {"extraction": _span("extraction", {
        "extraction_confidence": 0.95, "entities": {"parties": "not captured"}
    })}
    assert check(spans) is True


def test_garbled_doc_check_false_when_confidently_wrong():
    _, _, check = GROUND_TRUTH["garbled_scan_artifact.txt"]
    spans = {"extraction": _span("extraction", {
        "extraction_confidence": 0.95,
        "entities": {"parties": ["Totally Invented Vendor Inc"]},
    })}
    assert check(spans) is False


def test_clean_invoice_check_true_when_reference_matches():
    _, _, check = GROUND_TRUTH["clean_invoice.txt"]
    spans = {
        "extraction": _span("extraction", {"entities": {"reference_numbers": ["INV-2026-0417"]}}),
        "summarization": _span("summarization", {"summary": "Invoice INV-2026-0417 for $21,000."}),
    }
    assert check(spans) is True


def test_clean_invoice_check_false_when_reference_hallucinated():
    """Mirrors the real bug we found: summary cited INV-2026-0414 when
    extraction actually found INV-2026-0417."""
    _, _, check = GROUND_TRUTH["clean_invoice.txt"]
    spans = {
        "extraction": _span("extraction", {"entities": {"reference_numbers": ["INV-2026-0417"]}}),
        "summarization": _span("summarization", {"summary": "Invoice INV-2026-0414 for $21,000."}),
    }
    assert check(spans) is False
