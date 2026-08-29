# Case Study: What This Project's Own Tooling Found (and Fixed) in Its Own Pipeline

Findings 1-3 below come from `calibration_report.py` run against **50
recorded pipeline executions** across two independent batches (5 sample
documents x 5 runs, twice). Findings 4-5 come from scaling to a
50-document batch (Phase 6) and iterating on a real fix. All findings
used Ollama llama3.1 for both the pipeline and the judge.

## Headline numbers

- **17/50 runs (34%)**: the pipeline stated confidence >=4/5 while
  actually producing a wrong answer.
- **15/50 runs (30%)**: the LLM-as-judge's verdict disagreed with the
  known-correct answer for that document.

## Finding 1: A deterministic, shared blind spot

`ambiguous_category_doc.txt` is engineered to read as both a purchase
order and a contract. Across **10/10 runs** (two independent batches),
the classification step confidently (0.90) reported `ambiguous=False`
— wrong, every single time. And across those same **10/10 runs**, the
judge scored that classification 5/5 — also wrong, every time.

This isn't noise. It's a completely deterministic, reproducible pattern:
the judge and the pipeline were the same model (llama3.1). Judging "is
this document ambiguous?" is an interpretive call, not a factual check
— so the judge doesn't catch a mistake it would have made itself.
**This is a textbook argument for why an LLM-as-judge should be a
different (ideally stronger) model than the one it's evaluating**,
especially for subjective judgments.

## Finding 2: A high, real hallucination rate — and a noisier judge than first thought

`clean_invoice.txt` was designed as the "easy" baseline — no injected
failure mode. Yet across 10 runs, the summarization step **fabricated an
incorrect invoice number 7 times (70%)**, confidently citing
`INV-2026-0414` when extraction had correctly found `INV-2026-0417`.

The judge's performance on this specific error was inconsistent across
batches: it missed 2 of the first 3 occurrences, then caught all 4 in
the second batch. Combined, it caught **5 of 7 occurrences (71%)** —
meaningfully better than the first batch alone suggested (33%), but
still noisy enough that you can't fully trust a single run of judge
output to confirm a document is clean.

**In a real deployment, this means a fabricated reference number on the
simplest possible document would occur on the majority of runs, and a
roughly 1-in-3 chance that even automated review wouldn't catch it.**
That's the kind of failure a human reviewer skimming a "looks fine"
dashboard would never catch consistently — which is the entire reason
a tool like this needs to exist, and the entire reason a SINGLE
demo run is not enough evidence that a pipeline is working.

## Finding 3: The judge isn't just lenient — it's also sometimes too harsh

`currency_mismatch_receipt.txt` was correctly handled by the pipeline in
all 10 runs (the currency conflict was flagged every time). But the
judge false-positived on this correct output **3 of 10 times**, scoring
it a 3/5 and flagging a `context_loss` failure that wasn't actually
there. Miscalibration here isn't one-directional — across both findings
2 and 3, the judge is noisy in both directions, not just lenient.

## What held steady vs. what got revised with more data

- **Held steady, now stronger:** the ambiguity blind spot (still 100%
  reproducible failure + 100% judge miss, now over double the sample).
- **Revised upward:** the clean-invoice hallucination rate (60% -> 70%
  combined) — a real, high rate, not a fluke of one batch.
- **Revised upward (better than it looked):** the judge's catch rate on
  that same hallucination (33% -> 71% combined) — a reminder that
  small-sample findings about a *noisy* judge can look worse than the
  underlying reality, and that this project's own calibration tooling is
  what let us catch and correct that, rather than shipping the batch-1
  number as if it were final.

## What this demonstrates

- The pipeline's stated confidence is not a reliable substitute for
  ground truth — it can be consistently, confidently wrong.
- An LLM-as-judge is meaningfully better at catching **objective**
  errors (a wrong invoice number, checkable against source text) than
  **subjective** ones (whether something counts as "ambiguous") — but
  even on objective errors, a single run of the judge is noisy enough
  that you need repeated sampling to trust the result.
- Using the same model as both actor and judge measurably suppresses
  detection of the actor's own blind spots, and that suppression doesn't
  go away with more samples — it's structural, not random noise.
- None of this was found by eyeballing outputs — it required running
  the pipeline repeatedly, tracing every step, and measuring stated
  confidence and judge verdicts against known ground truth across
  multiple independent batches. That *measurement infrastructure* —
  and the discipline of updating conclusions as more data comes in
  rather than trusting the first batch — is what this project actually
  delivers.
- Not every gap is a calibration problem. Some are coverage gaps (a
  category of error nothing was ever instructed to check for), and some
  are architecture problems (asking an LLM to do something -- like
  arithmetic -- that fundamentally belongs in code). Distinguishing
  which kind of problem you're looking at determines whether the right
  fix is a better prompt, a different judge model, or bypassing the LLM
  entirely for that specific check.

## Finding 4: Prompting an LLM to "verify the math" doesn't work — even when it works on other logic

Scaling to a 50-document batch (Phase 6) surfaced a new document type:
`math_error_total.txt` states `400 x $3.75` but a total of `$2,200`
(the correct total is `$1,500`). The first fix attempt added an explicit
instruction to the summarization prompt: *"verify quantity x unit_price
== total, flag if they don't match."*

Result: it made things WORSE, not better. Before the prompt change, the
step at least flagged something (albeit the wrong reason — "unusually
large amounts"). After adding an explicit arithmetic-check instruction,
it flagged **nothing at all**. In the same test, a **date-order**
contradiction (`contradictory_dates.txt`, a delivery date before the
order date) was caught correctly and consistently by the same kind of
generic "flag risk indicators" instruction, both before and after the
change.

**The distinction that matters:** date-order comparison is a qualitative
judgment call an LLM can reason about in free-form generation. Multiplication
is not — it requires the model to actually compute a correct numeric
result inside a single forward pass, which local/smaller models are
unreliable at, no matter how explicitly you ask. This is a real,
measured example of a broader principle: **verifiable, deterministic
claims (arithmetic, exact matching, threshold comparisons) should be
implemented as code, not requested via prompt** — even when a
structurally similar-looking request (date ordering) works fine as a
prompt instruction. The two look like the same kind of "ask the model to
check something," but only one of them is actually the model's job.

## Finding 5: Even a deterministic fix has assumptions worth checking

The actual fix: extraction was changed to capture line items (quantity,
unit price, line total) as structured data, and a new deterministic
Python function (`check_line_item_arithmetic`) verifies
`quantity x unit_price == line_total` in code — no LLM involved, wired
to override the judge outright when it fires (`VERIFIED_ERROR` category,
judge not even called for that step).

This worked immediately on `math_error_total.txt`. But running it across
the full 50-document batch also flagged `negative_amount.txt` — a
legitimate credit memo (`50 x $42.00 = $2,100`, correctly stated as a
`-$2,100` refund). The deterministic check's original tolerance logic
didn't account for the sign flip being expected, valid behavior for a
credit/refund line, and flagged it as an arithmetic error.

**Even code you're certain is "guaranteed correct" only handles the
cases you thought to enumerate.** The fix (checking whether magnitude
matches with an opposite sign, and only flagging genuine magnitude
mismatches) is a two-line change — but the point stands: determinism
doesn't mean completeness. This is a smaller-scale instance of the exact
same lesson the rest of this case study is about, just moved from "LLM
judgment" down to "code someone was confident about."

## Finding 6: Self-consistency fixes variance, not bias

Phase 7 added judge self-consistency: run the judge 3 times per step,
take the median score and majority category, instead of trusting one
sample. This directly fixed the `currency_mismatch_receipt.txt`
flip-flopping documented in Finding 3 -- across two full re-runs after
the change, that document landed on a consistent 4/5 "correct" verdict
both times, where it had previously alternated between 3/5 (false
positive) and 5/5 depending on the run.

But the same two re-runs also surfaced a different, more stubborn
pattern on `garbled_scan_artifact.txt`. That document intentionally
contains the placeholder text `<<name not captured>>` (simulating
garbled OCR output) -- extraction correctly and faithfully transcribes
that placeholder, which is the right behavior. The judge should score
this 5/5. Instead, **all 3 samples in the consensus agreed** it was a
2/5 hallucination, in both full re-runs -- 6 out of 6 individual judge
calls, unanimous, wrong.

**This is the important distinction majority-vote judging exposed
rather than hid:** self-consistency only cancels out *random* noise --
cases where the judge is genuinely uncertain and lands on different
answers by chance. It does nothing for *systematic* bias, where the
model consistently misapplies the same flawed reasoning every time.
Unanimous agreement across samples is not the same thing as being
correct -- it just means the mistake is reproducible rather than random.
6/6 agreement here is the model confidently, repeatably misreading its
own instructions (the prompt explicitly says a placeholder like "not
captured" is honest reporting, not hallucination) -- not something more
sampling would ever fix, because every sample makes the same error.

**Diagnosed root cause:** the judge prompt's hallucination rule is being
applied too literally -- it seems to check whether the *exact output
string* is "supported by" the source text as a substring match, rather
than checking whether extraction *added information beyond* what the
source actually contains. Since the placeholder text is technically
present verbatim in the source, a stricter reading should pass it; the
judge appears to instead be pattern-matching on "value looks like
something that shouldn't be in a clean extraction" regardless of
whether it originated from the source or was invented.

This is left as a documented, un-fixed finding rather than patched --
it's a cleaner demonstration of the actual limits of self-consistency as
a technique than a quietly-fixed prompt would be, and the fix (tightening
the hallucination rule to explicitly handle placeholder/verbatim-copied
text) is understood and specified precisely enough to implement in a
follow-up pass.

## Next step this points to

Route the judge through a different, stronger model than the pipeline
(the codebase already supports this via `JUDGE_LLM_PROVIDER` in `.env`)
and re-run this exact calibration report to see whether judge
miscalibration drops — particularly on the ambiguity case, which is the
one most likely to benefit from a genuinely independent second opinion,
and which has now shown zero improvement across 10 consecutive runs
with a same-model judge.
