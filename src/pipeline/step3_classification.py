import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.pipeline.schemas import (
    IntakeOutput, ExtractionOutput, ClassificationOutput, DocumentType,
)
from src.utils.llm_client import get_llm
from src.utils.token_usage import get_token_usage

SYSTEM_PROMPT = """You classify business documents into exactly one of:
invoice, contract, receipt, purchase_order, unknown.

Respond with ONLY JSON:
{
  "document_type": "<one of the types above>",
  "confidence": <float 0.0-1.0>,
  "ambiguous": <true if the text plausibly matches more than one type>,
  "candidate_types": ["<type>", ...]   // only if ambiguous, else []
}
"""


def run_classification(
    intake_output: IntakeOutput, extraction_output: ExtractionOutput
) -> ClassificationOutput:
    llm = get_llm(temperature=0.0)
    context = (
        f"Document text:\n{intake_output.raw_text}\n\n"
        f"Extracted entities (may help or may be noisy):\n"
        f"{extraction_output.entities.model_dump_json()}"
    )
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=context)]
    response = llm.invoke(messages)
    input_tokens, output_tokens = get_token_usage(response)

    try:
        parsed = json.loads(_strip_code_fences(response.content))
        doc_type = DocumentType(parsed.get("document_type", "unknown"))
        candidates = [DocumentType(t) for t in parsed.get("candidate_types", [])]
        return ClassificationOutput(
            doc_id=intake_output.doc_id,
            document_type=doc_type,
            classification_confidence=float(parsed.get("confidence", 0.5)),
            ambiguous=bool(parsed.get("ambiguous", False)),
            candidate_types=candidates,
            raw_llm_response=response.content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except (json.JSONDecodeError, ValueError, KeyError):
        return ClassificationOutput(
            doc_id=intake_output.doc_id,
            document_type=DocumentType.UNKNOWN,
            classification_confidence=0.0,
            ambiguous=True,
            candidate_types=[],
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
