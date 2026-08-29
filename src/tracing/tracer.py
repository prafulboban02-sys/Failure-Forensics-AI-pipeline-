"""
One Tracer per pipeline run. record_step() wraps each step and writes a
span whether it succeeds or blows up.

Could've done this with decorators but kept it explicit instead - you can
read chain.py top to bottom and see exactly what's being recorded at each
point, no magic hiding what's happening.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Optional, Any
from src.tracing.schemas import Span
from src.tracing.storage import save_span


class Tracer:
    def __init__(self, doc_id: str, source_filename: str):
        self.trace_id = str(uuid.uuid4())
        self.doc_id = doc_id
        self.source_filename = source_filename

    @contextmanager
    def record_step(self, step_name: str, input_data: dict[str, Any]):
        """
        Usage:
            with tracer.record_step("extraction", {"raw_text": "..."}) as ctx:
                output = run_extraction(...)
                ctx["output_data"] = output.model_dump()
                ctx["confidence"] = round(output.extraction_confidence * 5)
                ctx["raw_llm_response"] = output.raw_llm_response
                ctx["input_tokens"] = output.input_tokens
                ctx["output_tokens"] = output.output_tokens

        On exception, a span with status="error" is still recorded before
        the exception propagates — a failure with no trace is useless.
        """
        ctx: dict[str, Any] = {
            "output_data": {},
            "confidence": None,
            "raw_llm_response": None,
            "prompt": None,
            "input_tokens": None,
            "output_tokens": None,
        }
        start = time.perf_counter()
        try:
            yield ctx
            latency_ms = (time.perf_counter() - start) * 1000
            span = Span(
                span_id=str(uuid.uuid4()),
                trace_id=self.trace_id,
                doc_id=self.doc_id,
                step_name=step_name,
                source_filename=self.source_filename,
                input_data=input_data,
                output_data=ctx["output_data"],
                prompt=ctx["prompt"],
                raw_llm_response=ctx["raw_llm_response"],
                input_tokens=ctx["input_tokens"],
                output_tokens=ctx["output_tokens"],
                latency_ms=round(latency_ms, 2),
                confidence=ctx["confidence"],
                status="ok",
            )
            save_span(span)
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            span = Span(
                span_id=str(uuid.uuid4()),
                trace_id=self.trace_id,
                doc_id=self.doc_id,
                step_name=step_name,
                source_filename=self.source_filename,
                input_data=input_data,
                output_data=ctx["output_data"],
                prompt=ctx["prompt"],
                raw_llm_response=ctx["raw_llm_response"],
                input_tokens=ctx["input_tokens"],
                output_tokens=ctx["output_tokens"],
                latency_ms=round(latency_ms, 2),
                confidence=ctx["confidence"],
                status="error",
                error_message=str(e),
            )
            save_span(span)
            raise
