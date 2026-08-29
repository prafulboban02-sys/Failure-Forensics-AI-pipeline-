import uuid
from src.pipeline.schemas import IntakeInput, IntakeOutput


def run_intake(input_data: IntakeInput) -> IntakeOutput:
    """No LLM call here — pure ingestion. Kept as its own step because it's
    still a place failures happen (empty files, encoding issues, truncation)."""
    text = input_data.raw_text.strip()
    return IntakeOutput(
        doc_id=str(uuid.uuid4())[:8],
        raw_text=text,
        char_count=len(text),
        source_filename=input_data.source_filename,
    )
