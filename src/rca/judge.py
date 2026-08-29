"""
Scores how well one pipeline step did its job, given only that step's own
input and output (plus the original document text for grounding).

I judge each step in isolation on purpose - not the whole trace at once.
Otherwise "propagation_error" doesn't mean anything: if a step behaved
reasonably given what it was handed, but what it was handed was already
garbage, the judge should say the fault is upstream, not pin it on this
step.

Update after running the calibration numbers a bunch: a single judge call
turned out to be pretty noisy - same document, different verdict on
different runs (see CASE_STUDY.md, the currency-mismatch flip-flopping).
So judge_step() now samples the judge a few times (JUDGE_SAMPLES, 3 by
default) and takes the median score / majority category instead of
trusting one shot. Costs more calls but the calibration report got a lot
more stable after this.
"""

import os
import json
from collections import Counter
from langchain_core.messages import HumanMessage, SystemMessage
from src.rca.schemas import JudgeVerdict, FailureCategory
from src.utils.llm_client import get_llm

CATEGORY_DEFINITIONS = """
Failure categories (choose exactly one):
- extraction_hallucination: the step INVENTED a plausible-looking value
  that is not actually supported by the source text (e.g. making up a
  name, date, or amount that doesn't appear anywhere in the source).
  IMPORTANT: explicitly reporting a field as missing, unknown, empty,
  "not captured", "TBD", or similar is NOT hallucination -- it is CORRECT,
  honest behavior when the source text genuinely lacks that information.
  Only penalize fabrication of a value that looks real but isn't grounded
  in the text.
- misclassification: the step assigned a wrong label/type, or wrongly
  reported certainty (e.g. claimed no ambiguity when the source text is
  genuinely ambiguous, or vice versa).
- propagation_error: the step's output is only bad BECAUSE its input was
  already bad/incomplete -- given what it received, its behavior was
  reasonable. The fault lies upstream, not in this step.
- context_loss: the step dropped, ignored, or failed to carry forward
  important information that WAS available to it (in the source text or
  its input), resulting in an incomplete or misleading output.
- none: this step did a good job. Use this whenever quality_score >= 4.
  This INCLUDES cases where the step correctly reported missing/unknown
  data instead of guessing -- that is good behavior, not a defect.
"""

JUDGE_SYSTEM_PROMPT = f"""You are a strict quality auditor for one step of
an AI document-processing pipeline. You will be shown:
1. The ORIGINAL SOURCE TEXT of the document (ground truth)
2. What this specific step RECEIVED as input
3. What this specific step PRODUCED as output

Score how well this step did its job on a 1-5 scale:
5 = excellent, fully correct and complete
4 = good, minor imperfection that doesn't affect downstream correctness
3 = borderline, a real quality issue but not clearly wrong
2 = poor, a concrete error a downstream step or human would need to catch
1 = failed, output is wrong, hallucinated, or unusable

{CATEGORY_DEFINITIONS}

Respond with ONLY JSON:
{{
  "quality_score": <int 1-5>,
  "category": "<one of: extraction_hallucination, misclassification, propagation_error, context_loss, none>",
  "reasoning": "<2-3 sentences, cite specific evidence from the text>",
  "specific_issues": ["<short phrase>", ...]
}}
"""


def _judge_step_once(
    step_name: str,
    source_text: str,
    input_data: dict,
    output_data: dict,
) -> JudgeVerdict:
    llm = get_llm(temperature=0.0, prefix="JUDGE_")

    context = (
        f"STEP BEING AUDITED: {step_name}\n\n"
        f"ORIGINAL SOURCE TEXT:\n{source_text}\n\n"
        f"WHAT THIS STEP RECEIVED AS INPUT:\n{json.dumps(input_data, indent=2, default=str)}\n\n"
        f"WHAT THIS STEP PRODUCED AS OUTPUT:\n{json.dumps(output_data, indent=2, default=str)}"
    )

    messages = [SystemMessage(content=JUDGE_SYSTEM_PROMPT), HumanMessage(content=context)]
    response = llm.invoke(messages)

    try:
        parsed = json.loads(_strip_code_fences(response.content))
        return JudgeVerdict(
            step_name=step_name,
            quality_score=int(parsed.get("quality_score", 3)),
            category=FailureCategory(parsed.get("category", "none")),
            reasoning=parsed.get("reasoning", ""),
            specific_issues=parsed.get("specific_issues", []),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        # The judge itself failing is a real event worth recording, not hiding.
        return JudgeVerdict(
            step_name=step_name,
            quality_score=3,
            category=FailureCategory.NONE,
            reasoning=f"[judge failed to produce parseable output: {e}]",
            specific_issues=["judge_parse_failure"],
        )


def judge_step(
    step_name: str,
    source_text: str,
    input_data: dict,
    output_data: dict,
    n_samples: int | None = None,
) -> JudgeVerdict:
    """
    Public entry point used everywhere else in the codebase. Runs the judge
    n_samples times (default from JUDGE_SAMPLES env var, falling back to 3)
    and returns a single aggregated verdict: median score, majority-vote
    category, reasoning from whichever sample landed on the median score.

    Set JUDGE_SAMPLES=1 in .env to disable this and match the original
    single-call behavior (faster, but reintroduces the noise the
    calibration report measured).
    """
    if n_samples is None:
        n_samples = int(os.getenv("JUDGE_SAMPLES", "3"))

    if n_samples <= 1:
        return _judge_step_once(step_name, source_text, input_data, output_data)

    verdicts = [
        _judge_step_once(step_name, source_text, input_data, output_data)
        for _ in range(n_samples)
    ]

    scores = sorted(v.quality_score for v in verdicts)
    median_score = scores[len(scores) // 2]

    category_counts = Counter(v.category for v in verdicts)
    majority_category, _ = category_counts.most_common(1)[0]

    # Prefer the reasoning from a verdict that actually landed on the
    # median score, so the explanation matches the score being reported.
    representative = next(
        (v for v in verdicts if v.quality_score == median_score), verdicts[0]
    )
    all_scores_str = ", ".join(str(v.quality_score) for v in verdicts)
    reasoning = (
        f"[Consensus of {n_samples} judge samples, scores: {all_scores_str}] "
        + representative.reasoning
    )

    all_issues = sorted(set(issue for v in verdicts for issue in v.specific_issues))

    return JudgeVerdict(
        step_name=step_name,
        quality_score=median_score,
        category=majority_category,
        reasoning=reasoning,
        specific_issues=all_issues,
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
