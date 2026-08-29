import json
from src.rca import judge as judge_module


def _verdict_json(score, category, reasoning="r", issues=None):
    return json.dumps({
        "quality_score": score,
        "category": category,
        "reasoning": reasoning,
        "specific_issues": issues or [],
    })


def test_single_sample_matches_original_behavior(monkeypatch, fake_llm_factory):
    """n_samples=1 should behave exactly like a single judge call -- no
    aggregation overhead when self-consistency is explicitly disabled."""
    fake_llm = fake_llm_factory(_verdict_json(2, "extraction_hallucination"))
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("extraction", "text", {}, {}, n_samples=1)

    assert verdict.quality_score == 2
    assert verdict.category.value == "extraction_hallucination"


def test_majority_vote_takes_median_score(monkeypatch, fake_llm_sequence_factory):
    """Scores of 2, 4, 5 across 3 samples -> median is 4."""
    fake_llm = fake_llm_sequence_factory([
        _verdict_json(2, "none"),
        _verdict_json(4, "none"),
        _verdict_json(5, "none"),
    ])
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("summarization", "text", {}, {}, n_samples=3)

    assert verdict.quality_score == 4


def test_majority_vote_takes_majority_category(monkeypatch, fake_llm_sequence_factory):
    """2 of 3 samples agree on context_loss -- that should win even though
    a lone dissenting sample said none."""
    fake_llm = fake_llm_sequence_factory([
        _verdict_json(3, "context_loss"),
        _verdict_json(3, "context_loss"),
        _verdict_json(5, "none"),
    ])
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("summarization", "text", {}, {}, n_samples=3)

    assert verdict.category.value == "context_loss"


def test_this_is_exactly_the_currency_false_positive_pattern(monkeypatch, fake_llm_sequence_factory):
    """Mirrors the real calibration finding: judge said 3/5 twice and 5/5
    three times across 5 real runs on currency_mismatch_receipt.txt.
    Self-consistency within a SINGLE analysis should smooth exactly this
    kind of single-sample noise instead of committing to one flaky score."""
    fake_llm = fake_llm_sequence_factory([
        _verdict_json(5, "none"),
        _verdict_json(3, "context_loss"),
        _verdict_json(5, "none"),
    ])
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("summarization", "text", {}, {}, n_samples=3)

    # Majority (2 of 3) says fine -- the lone harsh sample shouldn't win.
    assert verdict.quality_score == 5
    assert verdict.category.value == "none"


def test_reasoning_and_issues_are_aggregated(monkeypatch, fake_llm_sequence_factory):
    fake_llm = fake_llm_sequence_factory([
        _verdict_json(3, "context_loss", "first reasoning", ["issue_a"]),
        _verdict_json(3, "context_loss", "second reasoning", ["issue_b"]),
        _verdict_json(3, "context_loss", "third reasoning", ["issue_a"]),
    ])
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("summarization", "text", {}, {}, n_samples=3)

    assert "Consensus of 3 judge samples" in verdict.reasoning
    assert set(verdict.specific_issues) == {"issue_a", "issue_b"}


def test_env_var_controls_default_sample_count(monkeypatch, fake_llm_sequence_factory):
    monkeypatch.setenv("JUDGE_SAMPLES", "1")
    fake_llm = fake_llm_sequence_factory([_verdict_json(2, "misclassification")])
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm)

    verdict = judge_module.judge_step("classification", "text", {}, {})  # no explicit n_samples

    assert verdict.quality_score == 2
    assert "Consensus" not in verdict.reasoning  # single-sample path, no aggregation wrapper
