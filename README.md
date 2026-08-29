# Failure Forensics Tool for AI Pipelines

An observability layer for multi-step AI pipelines that traces every
intermediate step, identifies exactly where failures originate, and feeds
flagged failures into a growing evaluation dataset.

> **Status: All 6 core phases complete**, plus real hardening work found
> and fixed along the way (see `CASE_STUDY.md` for the full story: a
> deterministic ambiguity blind spot, a 70% hallucination rate on the
> "easy" baseline document, a failed prompt-only fix and the deterministic
> fix that replaced it, and a bug found in that fix's own edge cases).
> Tests: 56 passing. Phases 7-8 (further hardening + UI polish) are
> optional next steps, not required for the project to stand on its own.

## Why this project

When a multi-step AI pipeline produces garbage output, most teams have no
idea which step broke. This tool answers "where did this go wrong, and
why?" for a document-processing pipeline (Intake → Extraction →
Classification → Summarization).

## Architecture (Phase 1)

```
src/
  pipeline/
    schemas.py       # Pydantic I/O contracts for every step
    step1_intake.py
    step2_extraction.py     # LLM: pulls structured entities
    step3_classification.py # LLM: document type
    step4_summarization.py  # LLM: type-tailored summary
    chain.py          # orchestrator — catches failures per-step, not globally
  utils/
    llm_client.py     # single Claude/LangChain config point
data/
  sample_docs/
    generate_samples.py   # synthetic docs, each with ONE known injected failure
run_demo.py
```

Each pipeline step is a pure function with a typed input and output. This
matters for later phases: the root-cause analyzer (Phase 3) works by
diffing what a step *received* against what it *produced* — that's only
possible because the contracts are explicit and validated with Pydantic,
not loose dicts.

## Setup (local machine, VSCode)

1. **Clone/copy this folder** to your machine, open it in VSCode.

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Ollama (free, runs the LLM locally — no API key needed):**
   - Download from **https://ollama.com** and install it (Mac/Windows/Linux).
   - Pull a model (this downloads it once, ~4.7GB for llama3.1:8b):
     ```bash
     ollama pull llama3.1
     ```
   - Make sure Ollama is running (it usually starts automatically after
     install; `ollama serve` if not).

5. **Set up your `.env` file:**
   ```bash
   cp .env.example .env
   ```
   The default `.env` already points at `LLM_PROVIDER=ollama` with
   `OLLAMA_MODEL=llama3.1` — no key required. When you're ready to switch
   to Claude later, uncomment the `ANTHROPIC_API_KEY` / `PIPELINE_MODEL`
   lines, set `LLM_PROVIDER=anthropic`, and `pip install langchain-anthropic`.

6. **Create `.gitignore`** (if you haven't):
   ```
   venv/
   .env
   __pycache__/
   *.pyc
   traces/
   ```

7. **Run the demo:**
   ```bash
   python run_demo.py
   ```
   This runs all 5 sample documents through the full pipeline and prints
   what each step extracted, classified, and summarized — including the
   documents engineered to fail in specific ways (missing date, ambiguous
   category, currency mismatch, garbled OCR).

## The 5 sample documents (and their designed failure)

| File | Injected failure mode |
|---|---|
| `clean_invoice.txt` | None — baseline, should pass cleanly |
| `missing_date_invoice.txt` | No extractable date → extraction should return empty `dates[]` |
| `ambiguous_category_doc.txt` | Reads as both purchase order and contract → classification should flag `ambiguous=True` |
| `currency_mismatch_receipt.txt` | Currency symbol (EUR) contradicts amount-in-words (USD) |
| `garbled_scan_artifact.txt` | OCR-like garbage text → extraction confidence should be very low |

Once you run this, check whether the pipeline's confidence scores and flags
actually line up with these known-injected failures — that comparison is
your Phase 3 root-cause analyzer's ground truth.

## Phase 2: Tracing layer

```
src/tracing/
  schemas.py   # Span model: input, output, prompt, raw response, tokens,
               # latency, confidence (1-5), status, error
  storage.py   # persists each Span as traces/<trace_id>__<step>.json,
               # indexes it in traces/traces_index.db (SQLite)
  tracer.py    # Tracer: one per pipeline run. record_step() context
               # manager wraps each step, measuring latency and writing
               # a span on both success AND failure
inspect_traces.py   # CLI to query what's been captured
```

Every pipeline run gets a `trace_id`. Every step within that run gets a
`span_id`. Confidence is normalized to a 1–5 scale across all steps
(extraction/classification's existing 0–1 confidence is scaled; the new
summarization step now explicitly self-rates 1–5).

**Try it:**
```bash
python run_demo.py                       # runs pipeline, now prints trace_id
python inspect_traces.py                 # table of every span ever recorded
python inspect_traces.py --errors        # only failed steps
python inspect_traces.py --low-confidence  # confidence <= 2
python inspect_traces.py --trace <trace_id>  # full JSON for one run
```

Traces persist across runs (in `traces/`), so you can build up a history
and query across it — this is the dataset Phase 3's root-cause analyzer
will operate on.

## Phase 3: Root-cause analysis (the "forensics" part)

```
src/rca/
  schemas.py    # JudgeVerdict, RootCauseReport, FailureCategory enum
  judge.py      # LLM-as-judge: scores ONE step's output quality given
                # its input + the original source text
  analyzer.py   # walks a trace step-by-step in pipeline order; the
                # EARLIEST step scoring <= 3/5 is the root cause
  storage.py    # persists reports to rca_reports/<trace_id>.json,
                # indexed in rca_reports/rca_index.db
analyze_failures.py   # CLI
```

**Why judge each step in isolation:** the judge only sees one step's input
and output (plus the original source text) at a time -- not the whole
trace. This is what makes `propagation_error` a meaningful category: if a
step behaved reasonably given what it was handed, but what it was handed
was already corrupted by an earlier step, the judge says so. The **first**
step in pipeline order that scores badly is treated as the true root
cause; anything scoring badly after that is very likely just inheriting
the damage.

**Failure categories:**
| Category | Meaning |
|---|---|
| `extraction_hallucination` | Invented or misread data not supported by the source text |
| `misclassification` | Wrong type assigned, or wrongly confident/unconfident about ambiguity |
| `propagation_error` | This step did fine given its (already-bad) input -- fault is upstream |
| `context_loss` | Step dropped information that was actually available to it |
| `none` | Step is fine |

**Try it:**
```bash
python analyze_failures.py --all              # analyze every trace you've ever recorded
python analyze_failures.py --trace <trace_id> # analyze just one
python analyze_failures.py --all --unhealthy-only  # only show flagged ones
```

Go run `run_demo.py` a few times first (or you'll have no traces yet), then
run `analyze_failures.py --all` and see whether it correctly flags the
`ambiguous_category_doc.txt` misclassification we found by eye back in
Phase 2.

### A real lesson learned: same-model judges share blind spots

Running this for real surfaced something worth knowing rather than
hiding: with Ollama's llama3.1 driving both the pipeline AND the judge,
the judge consistently failed to flag `ambiguous_category_doc.txt`'s
classification as wrong (it kept scoring it 5/5), even though the
classifier consistently said `ambiguous=False` when the document is
genuinely ambiguous by design. The reason: judging "is this ambiguous?"
is a subjective call, and the same model made both the original judgment
and the judgment-of-the-judgment -- so it agreed with itself.

Meanwhile, the judge correctly and repeatedly caught a genuinely
*objective* error: the summarization step hallucinating a wrong invoice
number (`INV-2026-0414` vs. the actual `INV-2026-0417`) on the "easy"
clean invoice document -- because that's a factual check, not an
interpretive one, and any competent judge (same model or not) can verify
it against the source text.

**Takeaway:** LLM-as-judge is much more reliable for objective/factual
correctness checks than for subjective interpretive calls, and using the
same model as both actor and judge is a known failure mode for the
latter. `get_llm()` supports a `prefix="JUDGE_"` for exactly this reason
-- see `.env.example` for how to point the judge at a different (ideally
stronger) model than the pipeline once you have an API key.

### Confidence calibration

The real question a portfolio project should be able to answer: **when
this system says it's confident, is it actually right?**

```
data/sample_docs/ground_truth.py   # known-correct answer for each sample
                                    # document, checked programmatically
                                    # against whatever the pipeline
                                    # actually produced on a given run
calibration_report.py              # CLI: compares stated confidence AND
                                    # the judge's verdict against ground
                                    # truth, across EVERY run you've ever
                                    # recorded
```

**Try it** (works immediately on whatever traces you already have):
```bash
python calibration_report.py
```

This measures two different things:
1. **Pipeline calibration** — when a step says it's confident (>=4/5),
   is it actually correct? (High confidence + wrong answer = miscalibrated.)
2. **Judge calibration** — does the Phase 3 judge's verdict agree with
   the *known* correct answer? This is how we caught, systematically
   rather than by eye, that the judge kept missing the ambiguous-category
   misclassification (a subjective call) while reliably catching the
   hallucinated invoice number (an objective one).

With only 5 documents this is directional, not statistically rigorous --
but the mechanism is real and will produce a genuinely meaningful
reliability signal once Phase 6 runs it across 50 documents.

**See [`CASE_STUDY.md`](./CASE_STUDY.md) for a real, quantified writeup of
what a 25-run calibration analysis actually found** -- including a 60%
hallucination rate on the "easy" baseline document that the judge only
caught a third of the time. This is the single most CV/interview-worthy
artifact in the whole project.

## Phase 5: Feedback loop

```
src/feedback/
  schemas.py    # EvalCase, EvalRunResult
  storage.py    # eval_cases/<eval_id>.json + eval_cases/eval_index.db
generate_eval_cases.py   # scans trace history, auto-creates cases from
                         # known (ground-truth) failures
eval_runner.py           # RE-RUNS the pipeline fresh on each case's
                         # original document, checks if it's still
                         # failing, tracks resolution rate over time
```

Two ways a failure enters the eval set:
- **Automatically**, when a sample document with a known correct answer
  (`ground_truth.py`) fails on a run -- no human needed, `generate_eval_cases.py`
  catches it.
- **Manually**, via the "🚩 Flag this step's output" button at the bottom
  of the Trace Explorer's step inspector -- for real documents with no
  automatic oracle, a human confirms the failure. These are listed for
  review rather than auto pass/failed, since there's nothing to check
  them against.

**Try it:**
```bash
python generate_eval_cases.py   # build the eval set from trace history you already have
python eval_runner.py           # actually re-run the pipeline and check resolution
```

`eval_runner.py` is the piece that makes this a real regression test, not
just a log: it doesn't replay old data, it re-executes the pipeline on
the original document right now, producing a brand new fully-traced run,
and checks whether the known failure still reproduces. Run it again
after changing a prompt to see whether resolution rate actually moved.

The dashboard's third tab ("Eval Set") shows every tracked case, its
origin, run count, and resolution rate.

## Phase 6: 50-document batch demo

```
data/batch_docs/generate_batch_docs.py   # generates 50 documents:
                                          # 39 normal (varied vendors/
                                          # amounts/types), 11 each with a
                                          # DIFFERENT engineered failure
                                          # mode (beyond the original 5)
process_batch.py                         # runs all 50 through the full
                                          # pipeline + root-cause analysis,
                                          # prints a summary report
```

The 11 new engineered failures (on top of the original 5) cover genuinely
different territory: duplicate/conflicting reference numbers, arithmetic
that doesn't add up, a delivery date before the order date, a foreign-
language sentence embedded in an English document, a document that cuts
off mid-sentence, a suspiciously large amount, a document whose header
and body disagree on its own type, a missing vendor field entirely,
duplicate line items with different prices, a currency given only as a
symbol, and a negative-amount credit memo.

The 39 "normal" documents aren't padding -- per the calibration findings,
even ordinary-looking documents have a real, measured chance of
triggering an organic hallucination, so a chunk of the "real failures"
this batch finds will likely come from documents with no injected issue
at all.

**Try it:**
```bash
python data/batch_docs/generate_batch_docs.py
python process_batch.py
```
This will take a while for real (50 documents x ~4 LLM calls each for
the pipeline, then another ~3 judge calls each for root-cause analysis --
expect this to run for several minutes on local Ollama). It prints a
final summary: documents processed, how many were flagged, a breakdown
by failure category, and total/average time.

**Real measured result from a run of this batch** (Ollama llama3.1,
local machine): 50 documents processed, 2 flagged with a root cause
(both `verified_error` -- the deterministic arithmetic check from
Finding 4/5 in `CASE_STUDY.md`), total time 1200s (~12.4s average per
document to root-cause). Below the spec's original 8-10/50 target for
flagged documents -- worth being upfront about rather than
overclaiming. The likely explanation, and what CASE_STUDY.md digs into:
LLM-driven risk-flagging (the judge, and the summarization step's own
"flag risk indicators" instruction) reliably catches some failure
categories (date logic, currency mismatches) and reliably misses others
(arithmetic) regardless of how the prompt is worded -- which is itself
the most interesting finding in the whole project, not a shortfall to
paper over.

**Honest CV framing, using the real measured number:** "Built an
observability and root-cause-analysis tool for multi-step AI pipelines.
Diagnosed root causes automatically in ~12s per document on average
(vs. the manual alternative of reading through raw logs by hand) across
a 50-document batch, and used the tool's own calibration data to find,
diagnose, and fix a real reliability gap in the pipeline itself --
including catching a bug in the fix's own edge-case handling."

## Phase 7: Hardening (in progress)

**Judge self-consistency** (`src/rca/judge.py`): `judge_step()` now runs
the underlying single judge call (`_judge_step_once`) `JUDGE_SAMPLES`
times (default 3) and takes the median quality score and majority-vote
category, rather than trusting one sample. This directly targets a real
measured pattern from the calibration report: on
`currency_mismatch_receipt.txt`, the judge scored correct output 5/5
three times and incorrectly flagged it 3/5 twice, across the same 5
sample-document runs. A single call is a coin flip between those; taking
the median across 3 calls makes the lone-outlier score lose.

Trade-off: this triples judge LLM calls (and therefore `analyze_failures.py`
and `process_batch.py` runtime). Set `JUDGE_SAMPLES=1` in `.env` to
disable and go back to the original single-call behavior if you want
speed over reliability. See `tests/test_rca_judge_consistency.py` for
the majority-vote logic tested directly against the real currency-mismatch
noise pattern.

**Still open:** whether routing the judge through a different, stronger
model (`JUDGE_LLM_PROVIDER=anthropic`) actually resolves the
ambiguity blind spot from Finding 1 in `CASE_STUDY.md` — this needs a
real Anthropic API key to test (separate from a Claude.ai Pro
subscription, which does not include API access).

## Testing

Every pipeline step and the tracer/analyzer logic has automated tests
that **mock the LLM entirely** -- they run in under a second, cost
nothing, and don't require Ollama or an API key to be set up. This is
what actually gets checked before you'd ship a change, independent of
whatever the model happens to say on a given day.

```bash
python -m pytest
```

Tests cover: malformed JSON responses, empty/edge-case documents, the
pipeline stopping cleanly at whichever step fails, confidence normalization
staying within 1-5, and the analyzer picking the *earliest* failing step
rather than a downstream symptom.



## Phase 4: Visual trace explorer

```
dashboard.py   # streamlit run dashboard.py
```

Chose Streamlit over React specifically to avoid adding an npm/node
toolchain on top of everything else -- this is pure Python, same venv,
one command.

**Two tabs:**
1. **Trace Explorer** -- pick any run from the sidebar. The pipeline
   renders as 4 color-coded nodes (green healthy / yellow low confidence /
   red root cause or crashed). Click a step to see exactly what it
   received vs. what it produced, side by side, plus raw LLM response,
   tokens, latency, and the judge's verdict if one exists. A button
   triggers root-cause analysis on demand ("one-click flagging").
2. **Calibration Overview** -- a live, interactive version of
   `CASE_STUDY.md`. Same numbers, computed fresh from whatever traces
   you currently have on disk.

**Run it:**
```bash
streamlit run dashboard.py
```
This opens in your browser automatically (usually `http://localhost:8501`).
Needs existing traces to show anything -- run `python run_demo.py` a few
times first if you haven't already.

## Roadmap

- [x] **Phase 1 (Days 1–3):** Pipeline skeleton + failure-mode sample docs
- [x] **Phase 2 (Days 4–6):** Tracing layer — one span per step, capturing
      input, output, raw LLM response, token count, latency, errors, and a
      confidence score (1–5) the model assigns to its own output. Traces
      stored as JSON files indexed in SQLite.
- [x] **Phase 3 (Days 6–9):** Root-cause analysis — walk backward through
      spans on any flagged trace. LLM-as-judge scores each step's output
      quality given its input; the first step with a quality drop is the
      root cause. Categorize into: Extraction Hallucination,
      Misclassification, Propagation Error, Context Loss.
- [x] **Phase 4 (Days 9–11):** Visual trace explorer (Streamlit) —
      pipeline as nodes, color-coded green/yellow/red by health. Click a
      node to see full span details; diff view of expected vs. produced.
      One-click flagging runs the backward analysis and displays the
      diagnosis.
- [x] **Phase 5 (Days 11–13):** Feedback loop — every confirmed flag
      auto-generates an eval case (input, failing output, corrected
      output, failure category). Periodically re-run the eval dataset to
      track whether known failures are resolved.
- [x] **Phase 6 (Days 13–14):** Polish — process 50 documents, ensure
      8–10 real failures across different types. Demo: bad output in,
      trace explorer open, root cause diagnosed in seconds.
- [x] **Phase 7 (partial):** Hardening pass. Done: judge self-consistency
      (`JUDGE_SAMPLES`, default 3) -- runs the judge multiple times per
      step and takes the median score / majority category, directly
      targeting the currency-mismatch false-positive noise the
      calibration report measured; also fixed the deterministic
      arithmetic checker's own credit-memo edge case (see CASE_STUDY.md
      Finding 5). Still open: testing whether a stronger/different judge
      model (`JUDGE_LLM_PROVIDER=anthropic`) resolves the ambiguity blind
      spot -- needs an Anthropic API key to test, which is a separate
      signup/billing from a Claude.ai Pro subscription.
- [ ] **Phase 8:** Streamlit polish — visual/UX pass on `dashboard.py`:
      arrows between pipeline nodes, a run-history/trend view instead of
      one trace at a time, ability to upload and process a new document
      directly from the dashboard rather than only viewing past runs,
      general styling pass.

## CV framing (once complete)

> "Built an observability and root-cause-analysis tool for multi-step AI
> pipelines, reducing mean time to root-cause AI pipeline failures from
> hours of manual debugging to seconds of automated diagnosis."
