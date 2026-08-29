from src.pipeline.schemas import IntakeInput
from src.pipeline.step1_intake import run_intake


def test_intake_basic():
    result = run_intake(IntakeInput(raw_text="Hello world", source_filename="test.txt"))
    assert result.char_count == len("Hello world")
    assert result.source_filename == "test.txt"
    assert len(result.doc_id) == 8


def test_intake_strips_whitespace():
    result = run_intake(
        IntakeInput(raw_text="   padded text   \n", source_filename="test.txt")
    )
    assert result.raw_text == "padded text"


def test_intake_empty_document():
    """An empty file is a real failure mode this tool should surface, not crash on."""
    result = run_intake(IntakeInput(raw_text="   ", source_filename="empty.txt"))
    assert result.char_count == 0


def test_intake_doc_ids_are_unique():
    r1 = run_intake(IntakeInput(raw_text="a", source_filename="a.txt"))
    r2 = run_intake(IntakeInput(raw_text="a", source_filename="a.txt"))
    assert r1.doc_id != r2.doc_id
