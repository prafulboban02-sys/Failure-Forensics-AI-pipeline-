import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.pipeline.schemas import IntakeOutput, ExtractionOutput, ExtractedEntities, Currency, LineItem
from src.utils.llm_client import get_llm
from src.utils.token_usage import get_token_usage

SYSTEM_PROMPT = """You are an entity extraction engine for business documents.
Extract structured entities from the given text and respond with ONLY a JSON
object, no other text, matching this exact shape:

{
  "parties": ["<string>", ...],
  "dates": ["<string as found in text>", ...],
  "amounts": [<number>, ...],
  "currency": "USD" | "EUR" | "GBP" | "INR" | "UNKNOWN",
  "reference_numbers": ["<string>", ...],
  "line_items": [
    {
      "description": "<string or null>",
      "quantity": <number or null>,
      "unit_price": <number or null>,
      "line_total": <number or null>
    }, ...
  ],
  "confidence": <float 0.0-1.0, your own confidence in this extraction>
}

For line_items: extract EVERY quantity/unit-price/total combination you
find, exactly as stated in the text -- do not compute or correct
anything, just transcribe the numbers as written, even if they look
inconsistent to you. If a document has no clear line-item breakdown,
return an empty list.

If a field cannot be found, return an empty list for it. Do not invent data.
"""


def run_extraction(intake_output: IntakeOutput) -> ExtractionOutput:
    llm = get_llm(temperature=0.0)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=intake_output.raw_text),
    ]
    response = llm.invoke(messages)
    raw_text = response.content
    input_tokens, output_tokens = get_token_usage(response)

    try:
        parsed = json.loads(_strip_code_fences(raw_text))
        line_items = [
            LineItem(
                description=li.get("description"),
                quantity=li.get("quantity"),
                unit_price=li.get("unit_price"),
                line_total=li.get("line_total"),
            )
            for li in parsed.get("line_items", [])
        ]
        entities = ExtractedEntities(
            parties=parsed.get("parties", []),
            dates=parsed.get("dates", []),
            amounts=parsed.get("amounts", []),
            currency=Currency(parsed.get("currency", "UNKNOWN")),
            reference_numbers=parsed.get("reference_numbers", []),
            line_items=line_items,
        )
        confidence = float(parsed.get("confidence", 0.5))
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        # This IS a failure mode worth capturing, not swallowing.
        entities = ExtractedEntities()
        confidence = 0.0

    return ExtractionOutput(
        doc_id=intake_output.doc_id,
        entities=entities,
        extraction_confidence=confidence,
        raw_llm_response=raw_text,
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
