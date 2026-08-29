"""
Ground truth for the 5 sample documents. Each document was engineered
with a KNOWN correct answer for one specific pipeline step. This lets us
measure calibration: does the pipeline's/judge's stated confidence
actually track whether the output was correct?

Each entry: (relevant_step, description, check_fn).
check_fn(spans: dict[str, Span]) -> bool | None
    True  = pipeline got it right on this run
    False = pipeline got it wrong on this run
    None  = can't evaluate (relevant step didn't run / data missing)
"""


def _check_ambiguous_category(spans) -> bool | None:
    c = spans.get("classification")
    if c is None:
        return None
    return c.output_data.get("ambiguous") is True


def _check_missing_date_reported_honestly(spans) -> bool | None:
    e = spans.get("extraction")
    if e is None:
        return None
    return e.output_data.get("entities", {}).get("dates", None) == []


def _check_currency_mismatch_flagged(spans) -> bool | None:
    s = spans.get("summarization")
    if s is None:
        return None
    flags = s.output_data.get("key_risk_flags", [])
    text = " ".join(flags).lower()
    return "currency" in text and ("mismatch" in text or ("eur" in text and "usd" in text))


def _check_garbled_doc_flagged_low_quality(spans) -> bool | None:
    e = spans.get("extraction")
    if e is None:
        return None
    # Correct behavior on garbage OCR input: either honestly low confidence,
    # OR honestly reporting missing/unknown fields instead of inventing data.
    low_conf = e.output_data.get("extraction_confidence", 1.0) <= 0.85
    entities = e.output_data.get("entities", {})
    flagged_missing = any(
        "not captured" in str(v).lower() or "tbd" in str(v).lower() or v in ([], "")
        for v in entities.values()
    )
    return bool(low_conf or flagged_missing)


def _check_clean_invoice_no_hallucinated_reference(spans) -> bool | None:
    e = spans.get("extraction")
    s = spans.get("summarization")
    if e is None or s is None:
        return None
    ref_numbers = e.output_data.get("entities", {}).get("reference_numbers", [])
    if not ref_numbers:
        return None
    summary_text = s.output_data.get("summary", "")
    # The summary should reference the SAME number extraction found --
    # not a fabricated, similar-looking one.
    return ref_numbers[0] in summary_text


GROUND_TRUTH = {
    "ambiguous_category_doc.txt": (
        "classification",
        "Document plausibly reads as both a purchase order and a contract "
        "-- classification should report ambiguous=True.",
        _check_ambiguous_category,
    ),
    "missing_date_invoice.txt": (
        "extraction",
        "No invoice date appears anywhere in the source text -- extraction "
        "should honestly report an empty dates[] rather than inventing one.",
        _check_missing_date_reported_honestly,
    ),
    "currency_mismatch_receipt.txt": (
        "summarization",
        "Currency symbol (EUR) contradicts amount-in-words (USD) -- this "
        "should surface as a risk flag in the summary.",
        _check_currency_mismatch_flagged,
    ),
    "garbled_scan_artifact.txt": (
        "extraction",
        "Source text is OCR garbage -- extraction should either report low "
        "confidence or honestly flag fields it couldn't read, not invent "
        "clean-looking data.",
        _check_garbled_doc_flagged_low_quality,
    ),
    "clean_invoice.txt": (
        "summarization",
        "The summary should cite the SAME reference number extraction "
        "found, not a fabricated, similar-looking one.",
        _check_clean_invoice_no_hallucinated_reference,
    ),
}
