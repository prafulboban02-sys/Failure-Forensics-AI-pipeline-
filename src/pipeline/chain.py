"""
Runs the 4 pipeline steps in order and wraps each one in a traced span.

I went back and forth on whether to wrap the whole thing in one big
try/except, but that defeats the purpose - you'd know the pipeline broke
somewhere but not where. Each step gets its own try/except instead, so a
failure at step 2 doesn't also swallow whatever step 3 would've told us.
"""

from src.pipeline.schemas import IntakeInput, PipelineResult
from src.pipeline.step1_intake import run_intake
from src.pipeline.step2_extraction import run_extraction
from src.pipeline.step3_classification import run_classification
from src.pipeline.step4_summarization import run_summarization
from src.pipeline.arithmetic_check import check_line_item_arithmetic
from src.tracing.tracer import Tracer


def run_pipeline(raw_text: str, source_filename: str) -> PipelineResult:
    # --- Step 1: Intake (no LLM call, but still worth a span: empty-file /
    # encoding issues are real failure modes) ---
    intake_output = run_intake(
        IntakeInput(raw_text=raw_text, source_filename=source_filename)
    )

    tracer = Tracer(doc_id=intake_output.doc_id, source_filename=source_filename)

    with tracer.record_step("intake", {"source_filename": source_filename}) as ctx:
        ctx["output_data"] = intake_output.model_dump()
        ctx["confidence"] = 5 if intake_output.char_count > 0 else 1

    result = PipelineResult(
        doc_id=intake_output.doc_id,
        trace_id=tracer.trace_id,
        source_filename=source_filename,
        intake=intake_output,
    )

    # --- Step 2: Extraction ---
    try:
        with tracer.record_step(
            "extraction", {"raw_text": intake_output.raw_text}
        ) as ctx:
            extraction_output = run_extraction(intake_output)
            ctx["output_data"] = extraction_output.model_dump()
            ctx["confidence"] = max(1, round(extraction_output.extraction_confidence * 5))
            ctx["raw_llm_response"] = extraction_output.raw_llm_response
            ctx["input_tokens"] = extraction_output.input_tokens
            ctx["output_tokens"] = extraction_output.output_tokens
        result.extraction = extraction_output
    except Exception as e:
        result.failed_at_step = "extraction"
        result.error_message = str(e)
        return result

    # --- Step 3: Classification ---
    try:
        with tracer.record_step(
            "classification",
            {
                "raw_text": intake_output.raw_text,
                "entities": extraction_output.entities.model_dump(),
            },
        ) as ctx:
            classification_output = run_classification(intake_output, extraction_output)
            ctx["output_data"] = classification_output.model_dump()
            ctx["confidence"] = max(
                1, round(classification_output.classification_confidence * 5)
            )
            ctx["raw_llm_response"] = classification_output.raw_llm_response
            ctx["input_tokens"] = classification_output.input_tokens
            ctx["output_tokens"] = classification_output.output_tokens
        result.classification = classification_output
    except Exception as e:
        result.failed_at_step = "classification"
        result.error_message = str(e)
        return result

    # --- Step 4: Summarization ---
    try:
        with tracer.record_step(
            "summarization",
            {
                "raw_text": intake_output.raw_text,
                "entities": extraction_output.entities.model_dump(),
                "document_type": classification_output.document_type.value,
            },
        ) as ctx:
            summarization_output = run_summarization(
                intake_output, extraction_output, classification_output
            )
            # Deterministic, code-based check -- NOT delegated to the LLM.
            # Guaranteed correct regardless of what the model did or didn't notice.
            summarization_output.verified_risk_flags = check_line_item_arithmetic(
                extraction_output.entities
            )
            ctx["output_data"] = summarization_output.model_dump()
            ctx["confidence"] = summarization_output.self_confidence
            ctx["raw_llm_response"] = summarization_output.raw_llm_response
            ctx["input_tokens"] = summarization_output.input_tokens
            ctx["output_tokens"] = summarization_output.output_tokens
        result.summarization = summarization_output
    except Exception as e:
        result.failed_at_step = "summarization"
        result.error_message = str(e)
        return result

    return result
