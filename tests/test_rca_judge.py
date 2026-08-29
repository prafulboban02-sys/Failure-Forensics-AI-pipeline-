import json
from src.rca import judge as judge_module


def test_judge_parses_valid_response(monkeypatch, fake_llm_factory):
    fake_response = json.dumps({
        "quality_score": 2,
        "category": "extraction_hallucination",
        "reasoning": "The extracted amount does not appear anywhere in the source text.",
        "specific_issues": ["fabricated_amount"],
    })
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm_factory(fake_response))

    verdict = judge_module.judge_step(
        step_name="extraction",
        source_text="Invoice for consulting services.",
        input_data={"raw_text": "Invoice for consulting services."},
        output_data={"amounts": [99999.0]},
    )

    assert verdict.quality_score == 2
    assert verdict.category.value == "extraction_hallucination"
    assert "fabricated_amount" in verdict.specific_issues


def test_judge_handles_malformed_response_gracefully(monkeypatch, fake_llm_factory):
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm_factory("not valid json"))

    verdict = judge_module.judge_step(
        step_name="classification",
        source_text="some text",
        input_data={},
        output_data={},
    )

    # Should degrade gracefully rather than crash the whole analysis run.
    assert verdict.quality_score == 3
    assert "judge_parse_failure" in verdict.specific_issues


def test_judge_strips_code_fences(monkeypatch, fake_llm_factory):
    fake_response = "```json\n" + json.dumps({
        "quality_score": 5, "category": "none", "reasoning": "fine", "specific_issues": [],
    }) + "\n```"
    monkeypatch.setattr(judge_module, "get_llm", lambda temperature=0.0, prefix="": fake_llm_factory(fake_response))

    verdict = judge_module.judge_step("summarization", "text", {}, {})
    assert verdict.quality_score == 5
