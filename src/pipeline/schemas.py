"""
Pydantic models for what goes in/out of each pipeline step.

I made these strict on purpose. Early on I had extraction just returning
a plain dict and it made debugging miserable - you'd get a KeyError three
steps later with no idea where the bad data actually came from. With
typed schemas, a step either returns something valid or it doesn't, and
the tracer can log exactly what was expected vs what showed up. That's
basically the whole trick behind the root-cause analyzer later on.
"""

from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# shared enums

class DocumentType(str, Enum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    UNKNOWN = "unknown"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    INR = "INR"
    UNKNOWN = "UNKNOWN"


# step 1: intake

class IntakeInput(BaseModel):
    raw_text: str
    source_filename: str


class IntakeOutput(BaseModel):
    doc_id: str
    raw_text: str
    char_count: int
    source_filename: str


# step 2: extraction (llm pulls structured entities)

class LineItem(BaseModel):
    """
    Structured enough that arithmetic can be VERIFIED IN CODE, not asked
    of an LLM. Small/local models are unreliable at multiplication inside
    free-form generation -- this is what lets us check it deterministically
    instead of trusting the model to "please verify the math."
    """
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None


class ExtractedEntities(BaseModel):
    """
    Fields are deliberately Optional — a real extraction step will often fail
    to find a value. Forcing everything to be required just hides failures
    behind exceptions instead of surfacing them as diagnosable data.
    """
    parties: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)  # raw strings; validated downstream
    amounts: list[float] = Field(default_factory=list)
    currency: Currency = Currency.UNKNOWN
    reference_numbers: list[str] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("dates")
    @classmethod
    def flag_missing(cls, v):
        return v  # kept as a hook point; real validation happens in root-cause step


class ExtractionOutput(BaseModel):
    doc_id: str
    entities: ExtractedEntities
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    raw_llm_response: str  # kept for forensic replay
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# step 3: classification (document type)

class ClassificationOutput(BaseModel):
    doc_id: str
    document_type: DocumentType
    classification_confidence: float = Field(ge=0.0, le=1.0)
    ambiguous: bool = False
    candidate_types: list[DocumentType] = Field(default_factory=list)
    raw_llm_response: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# step 4: summarization (tailored to document type)

class SummarizationOutput(BaseModel):
    doc_id: str
    summary: str
    key_risk_flags: list[str] = Field(default_factory=list)
    verified_risk_flags: list[str] = Field(default_factory=list)  # deterministic, code-checked -- not LLM-judged
    self_confidence: int = Field(default=3, ge=1, le=5)  # model's own 1-5 self-rating
    raw_llm_response: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# full pipeline result bundle (what gets traced/stored)

class PipelineResult(BaseModel):
    doc_id: str
    trace_id: Optional[str] = None
    source_filename: str
    intake: IntakeOutput
    extraction: Optional[ExtractionOutput] = None
    classification: Optional[ClassificationOutput] = None
    summarization: Optional[SummarizationOutput] = None
    failed_at_step: Optional[str] = None
    error_message: Optional[str] = None
