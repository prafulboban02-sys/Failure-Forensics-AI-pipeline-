import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.pipeline.schemas import (
    IntakeOutput, ExtractionOutput, ClassificationOutput, SummarizationOutput,
)
from src.utils.llm_client import get_llm
from src.utils.token_usage import get_token_usage

SYSTEM_PROMPT_TEMPLATE = """You write a 2-3 sentence summary of a {doc_type}
document for a busy operations reviewer. Also flag any risk indicators.

Check specifically for EACH of the following, and flag any that apply:
- Missing dates, currency mismatches, unusually large amounts, or
  ambiguous parties.
- ARITHMETIC CONSISTENCY: if the document states a quantity, a unit
  price, AND a total, verify that quantity x unit_price actually equals
  the stated total (allow small rounding, e.g. under $1). If it does
  NOT match, you MUST flag this explicitly, e.g. "Total does not match
  quantity x unit price (expected $X, stated $Y)".
- DATE LOGIC: if the document has more than one date (e.g. an order
  date and a delivery/due date), check whether their order makes sense
  (e.g. a delivery date should not be before the order date). Flag any
  contradiction explicitly.

Do not skip the arithmetic check just because the document otherwise
looks clean -- compute it every time quantity, unit price, and a total
are all present.

Respond with ONLY JSON:
{{
  "summary": "<string>",
  "key_risk_flags": ["<string>", ...],
  "self_confidence": <integer 1-5, how confident you are that this summary
                       is accurate and complete given the input. 1 = very
                       unsure / input was too ambiguous or incomplete,
                       5 = fully confident>
}}
"""


def run_summarization(
    intake_output: IntakeOutput,
    extraction_output: ExtractionOutput,
    classification_output: ClassificationOutput,
) -> SummarizationOutput:
    llm = get_llm(temperature=0.2)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        doc_type=classification_output.document_type.value
    )
    context = (
        f"Document text:\n{intake_output.raw_text}\n\n"
        f"Extracted entities:\n{extraction_output.entities.model_dump_json()}"
    )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=context)]
    response = llm.invoke(messages)
    input_tokens, output_tokens = get_token_usage(response)

    try:
        parsed = json.loads(_strip_code_fences(response.content))
        self_confidence = int(parsed.get("self_confidence", 3))
        self_confidence = max(1, min(5, self_confidence))  # clamp defensively
        return SummarizationOutput(
            doc_id=intake_output.doc_id,
            summary=parsed.get("summary", ""),
            key_risk_flags=parsed.get("key_risk_flags", []),
            self_confidence=self_confidence,
            raw_llm_response=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except (json.JSONDecodeError, ValueError):
        return SummarizationOutput(
            doc_id=intake_output.doc_id,
            summary="[summarization failed to parse]",
            key_risk_flags=["summarization_parse_failure"],
            self_confidence=1,
            raw_llm_response=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
