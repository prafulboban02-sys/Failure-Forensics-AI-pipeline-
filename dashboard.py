"""
Streamlit dashboard for browsing pipeline runs and diagnoses.

streamlit run dashboard.py

Three tabs: Trace Explorer (pick a run, see the pipeline steps as
color-coded boxes, click into any step's actual input/output), Calibration
Overview (a live version of CASE_STUDY.md), and Eval Set (tracked
failures, re-testable over time).

Went with Streamlit over a React frontend mainly to avoid dragging a
whole npm/node toolchain into a project that was already fighting enough
Windows/venv issues. Same language, same venv, one command to run it.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from src.tracing.storage import get_connection, query_spans, load_span
from src.rca.storage import load_report_by_trace_id, save_report
from src.rca.analyzer import analyze_trace
from src.pipeline.chain import run_pipeline
from src.feedback.schemas import EvalCase, EvalRunResult
from src.feedback.storage import save_eval_case, list_eval_cases, load_eval_case_by_id
from data.sample_docs.ground_truth import GROUND_TRUTH

STEP_ORDER = ["intake", "extraction", "classification", "summarization"]
COLOR_HEX = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444", "none": "#6b7280"}
EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "none": "⚪"}

st.set_page_config(page_title="Failure Forensics", page_icon="🔍", layout="wide")


def get_all_traces():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trace_id, source_filename, MIN(timestamp) as ts "
            "FROM spans GROUP BY trace_id ORDER BY ts DESC"
        ).fetchall()
    return rows


def step_status(step_name, span, report):
    if span is None:
        return "none"
    if span.status == "error":
        return "red"
    if report and not report.pipeline_healthy and report.root_cause_step == step_name:
        return "red"
    if span.confidence is not None and span.confidence <= 3:
        return "yellow"
    return "green"


def _render_document_history(filename, current_trace_id):
    """
    Same document, run more than once, can behave differently each time
    (see CASE_STUDY.md — clean_invoice.txt hallucinates a wrong reference
    number on a real, measured share of runs, not every run). Looking at
    one trace at a time hides that pattern completely. This shows every
    past run of THIS document side by side so it's visible at a glance.
    """
    all_runs = get_all_traces()
    same_doc_runs = [(tid, ts) for tid, fn, ts in all_runs if fn == filename]

    if len(same_doc_runs) < 2:
        st.caption(
            f"This is the only recorded run of `{filename}` so far — run "
            f"`python run_demo.py` a few more times to build up a history."
        )
        return

    st.subheader(f"History for `{filename}`")
    st.caption(
        f"{len(same_doc_runs)} recorded runs of this exact document. Confidence "
        f"and outcome can genuinely differ run to run — that variance is itself "
        f"a finding, not noise to ignore."
    )

    rows = []
    for tid, ts in same_doc_runs:
        span_rows = query_spans(trace_id=tid)
        run_spans = {r["step_name"]: load_span(r["json_path"]) for r in span_rows}
        run_report = load_report_by_trace_id(tid)
        row = {"trace": tid[:8] + ("  (this run)" if tid == current_trace_id else "")}
        for step in STEP_ORDER:
            s = run_spans.get(step)
            row[step] = s.confidence if s and s.confidence is not None else None
        row["outcome"] = (
            "🔴 flagged" if run_report and not run_report.pipeline_healthy
            else "🟢 healthy" if run_report
            else "⚪ not analyzed"
        )
        rows.append(row)

    st.dataframe(rows, use_container_width=True, hide_index=True)

    try:
        import pandas as pd
        chart_df = pd.DataFrame(rows).set_index("trace")[STEP_ORDER]
        st.line_chart(chart_df, height=200)
        st.caption("Confidence per step across these runs — a flat line means consistent behavior, a jagged one means the model isn't stable on this document.")
    except Exception:
        pass  # chart is a nice-to-have, table above already shows the same data


def render_trace_explorer():
    traces = get_all_traces()
    if not traces:
        st.info(
            "👋 No runs recorded yet — this dashboard shows what happened to "
            "documents you've already processed. To see it in action:\n\n"
            "1. Open a terminal in this project folder\n"
            "2. Run `python run_demo.py` (processes 5 sample documents)\n"
            "3. Refresh this page — your runs will appear in the sidebar"
        )
        return

    trace_options = {f"{fn}  —  {tid[:8]}  ({ts})": tid for tid, fn, ts in traces}
    filename_by_trace_id = {tid: fn for tid, fn, ts in traces}
    st.sidebar.caption("Each entry below is one document run through the full pipeline.")
    selected_label = st.sidebar.selectbox("Select a run to inspect", list(trace_options.keys()))
    trace_id = trace_options[selected_label]

    if st.session_state.get("_current_trace") != trace_id:
        st.session_state["_current_trace"] = trace_id

    rows = query_spans(trace_id=trace_id)
    spans = {r["step_name"]: load_span(r["json_path"]) for r in rows}
    report = load_report_by_trace_id(trace_id)

    # Ground truth check, if this document has a known correct answer.
    gt_relevant_step, gt_description, gt_result = None, None, None
    current_filename = filename_by_trace_id.get(trace_id)
    if current_filename in GROUND_TRUTH:
        gt_relevant_step, gt_description, check_fn = GROUND_TRUTH[current_filename]
        gt_result = check_fn(spans)

    st.subheader("Pipeline")
    st.caption(
        "Each box below is one processing step, in order left to right. "
        "🟢 = did its job well  🟡 = low self-reported confidence  🔴 = crashed, or identified as the root cause of a problem"
    )

    # Interleave a narrow arrow column between each step so the diagram
    # reads as a left-to-right flow, not 4 disconnected boxes.
    col_widths = []
    for i in range(len(STEP_ORDER)):
        col_widths.append(6)
        if i < len(STEP_ORDER) - 1:
            col_widths.append(1)
    cols = st.columns(col_widths)
    box_cols = cols[0::2]
    statuses = {}
    for i, step in enumerate(STEP_ORDER):
        span = spans.get(step)
        status = step_status(step, span, report)
        statuses[step] = status
        conf_str = f"{span.confidence}/5" if span and span.confidence is not None else "—"

        gt_badge = ""
        if step == gt_relevant_step and gt_result is not None:
            if gt_result:
                gt_badge = '<div style="margin-top:6px; font-size:12px; color:#16a34a;">🎯 ground truth: correct</div>'
            else:
                gt_badge = '<div style="margin-top:6px; font-size:12px; color:#dc2626; font-weight:600;">🎯 ground truth: WRONG</div>'

        with box_cols[i]:
            st.markdown(
                f"""
                <div style="background-color:{COLOR_HEX[status]}22; border:2px solid {COLOR_HEX[status]};
                            border-radius:10px; padding:16px; text-align:center;">
                    <div style="font-size:26px;">{EMOJI[status]}</div>
                    <div style="font-weight:600; margin-top:4px;">{step}</div>
                    <div style="font-size:13px; opacity:0.75;">confidence: {conf_str}</div>
                    {gt_badge}
                </div>
                """,
                unsafe_allow_html=True,
            )
        if i < len(STEP_ORDER) - 1:
            with cols[2 * i + 1]:
                st.markdown(
                    '<div style="text-align:center; font-size:22px; padding-top:28px; opacity:0.4;">→</div>',
                    unsafe_allow_html=True,
                )

    st.write("")

    # The most valuable signal: does the judge/pipeline's own assessment
    # disagree with the KNOWN correct answer for this document?
    if gt_result is not None:
        judge_verdict_for_gt_step = None
        if report:
            judge_verdict_for_gt_step = next(
                (v for v in report.step_verdicts if v.step_name == gt_relevant_step), None
            )
        judge_says_healthy = (
            judge_verdict_for_gt_step is None or judge_verdict_for_gt_step.quality_score >= 4
        )

        if gt_result is False and judge_says_healthy:
            st.warning(
                f"⚠️ **Ground truth mismatch on `{gt_relevant_step}`:** this document has a "
                f"known-correct answer that the pipeline got WRONG, but "
                + ("no root-cause analysis has flagged it yet." if report is None
                   else "the judge scored this step as healthy anyway (a miss).")
                + f"\n\n*What we expect:* {gt_description}"
            )
        elif gt_result is True and not judge_says_healthy:
            st.warning(
                f"⚠️ **Judge may be a false positive on `{gt_relevant_step}`:** the pipeline's "
                f"answer actually matches the known-correct behavior, but the judge flagged "
                f"this step as low quality anyway."
                f"\n\n*What we expect:* {gt_description}"
            )
        elif gt_result is False:
            st.info(f"🎯 Known issue on `{gt_relevant_step}`, correctly flagged by the judge. *Expected:* {gt_description}")
        else:
            st.caption(f"🎯 Ground truth check available for `{gt_relevant_step}`: pipeline got it right this run. *Expected:* {gt_description}")

    if report:
        if report.pipeline_healthy:
            st.success("No issues found on last analysis — all steps scored acceptably.")
        else:
            st.error(
                f"**ROOT CAUSE: {report.root_cause_step}**  —  "
                f"category: `{report.root_cause_category.value}`\n\n"
                f"{report.root_cause_explanation}"
            )
    else:
        st.info("This trace hasn't been analyzed yet.")

    if st.button("🔬 Run / Re-run Root-Cause Analysis", type="primary"):
        with st.spinner("Judging each step (calls your local LLM, may take a minute)..."):
            try:
                report = analyze_trace(trace_id)
                save_report(report)
                st.rerun()
            except Exception as e:
                st.error(
                    "Couldn't reach an LLM to run this. This feature needs Ollama "
                    "running locally, or an Anthropic API key configured — it won't "
                    "work on a hosted demo with no model behind it.\n\n"
                    f"Details: {e}"
                )

    st.divider()
    _render_document_history(current_filename, trace_id)

    st.divider()

    st.subheader("Inspect a step")
    st.caption(
        "Pick a step to see exactly what it was given and what it produced, "
        "side by side — this is the actual evidence, not a summary of it."
    )
    available_steps = [s for s in STEP_ORDER if s in spans]
    selected_step = st.radio(
        "step selector",
        available_steps,
        format_func=lambda s: f"{EMOJI[statuses[s]]}  {s}",
        horizontal=True,
        label_visibility="collapsed",
    )
    span = spans[selected_step]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📥 What this step received (input)**")
        st.json(span.input_data)
    with col2:
        st.markdown("**📤 What this step produced (output)**")
        st.json(span.output_data)

    with st.expander("Raw metadata"):
        st.write(f"**Status:** {span.status}")
        if span.error_message:
            st.write(f"**Error:** {span.error_message}")
        st.write(f"**Latency:** {span.latency_ms:.0f}ms")
        st.write(f"**Tokens:** in={span.input_tokens}, out={span.output_tokens}")
        st.write(f"**Confidence:** {span.confidence}/5")
        if span.raw_llm_response:
            st.markdown("**Raw LLM response:**")
            st.code(span.raw_llm_response)

    if report:
        verdict = next((v for v in report.step_verdicts if v.step_name == selected_step), None)
        if verdict:
            st.markdown("**🧑‍⚖️ Judge verdict for this step**")
            st.caption("A separate AI review of this step's output — independent of the step's own self-reported confidence above.")
            st.write(f"Score: **{verdict.quality_score}/5**  —  category: `{verdict.category.value}`")
            st.write(verdict.reasoning)
            if verdict.specific_issues:
                st.write("Issues: " + ", ".join(verdict.specific_issues))

    st.divider()
    st.markdown("**🚩 Not sure the judge got this right? Flag it for the eval set.**")
    st.caption(
        "For real documents with no automatic ground truth, this is how a human "
        "confirms a failure so it gets tracked and re-checked over time (Phase 5)."
    )
    note = st.text_input(
        "Optional note: what should have happened instead?",
        key=f"flag_note_{trace_id}_{selected_step}",
    )
    if st.button("Flag this step's output as a confirmed failure", key=f"flag_btn_{trace_id}_{selected_step}"):
        category = verdict.category.value if report and verdict else "manual"
        case = EvalCase(
            eval_id=f"manual::{trace_id[:8]}::{selected_step}",
            source_filename=span.source_filename,
            relevant_step=selected_step,
            failure_category=category,
            description=note or "Manually flagged from the dashboard -- no ground truth oracle available.",
            original_input=span.input_data,
            example_failing_output=span.output_data,
            corrected_note=note or None,
            origin="manual_flag",
            created_from_trace_id=trace_id,
        )
        case.run_history.append(EvalRunResult(trace_id=trace_id, resolved=False))
        save_eval_case(case)
        st.success(f"Added to eval set as `{case.eval_id}`. Run `python eval_runner.py` to track it going forward.")


def render_calibration_overview():
    st.subheader("Calibration: is stated confidence — or the judge — trustworthy?")
    st.caption(
        "Live version of CASE_STUDY.md. Compares stated confidence and the "
        "judge's verdict against the KNOWN correct answer for each sample "
        "document, across every run you've recorded."
    )

    traces = get_all_traces()
    table_rows = []
    pipeline_miscal = 0
    judge_miscal = 0
    evaluable = 0

    for trace_id, filename, _ts in traces:
        if filename not in GROUND_TRUTH:
            continue
        relevant_step, _desc, check_fn = GROUND_TRUTH[filename]
        rows = query_spans(trace_id=trace_id)
        spans = {r["step_name"]: load_span(r["json_path"]) for r in rows}

        is_correct = check_fn(spans)
        if is_correct is None:
            continue
        evaluable += 1

        step_span = spans.get(relevant_step)
        stated_conf = step_span.confidence if step_span else None

        report = load_report_by_trace_id(trace_id)
        judge_score = None
        judge_agrees = None
        if report:
            verdict = next((v for v in report.step_verdicts if v.step_name == relevant_step), None)
            if verdict:
                judge_score = verdict.quality_score
                judge_agrees = (judge_score >= 4) == is_correct

        if stated_conf is not None and stated_conf >= 4 and not is_correct:
            pipeline_miscal += 1
        if judge_agrees is False:
            judge_miscal += 1

        table_rows.append({
            "file": filename,
            "trace": trace_id[:8],
            "step": relevant_step,
            "stated confidence": f"{stated_conf}/5" if stated_conf is not None else "—",
            "ground truth": "correct" if is_correct else "WRONG",
            "judge score": f"{judge_score}/5" if judge_score is not None else "not analyzed",
            "judge agrees?": "—" if judge_agrees is None else ("yes" if judge_agrees else "NO"),
        })

    if not table_rows:
        st.warning(
            "No evaluable runs yet. Run `python run_demo.py` and "
            "`python analyze_failures.py --all` first, then refresh."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Evaluable runs", evaluable, help="Runs where we actually know the correct answer ahead of time, so we can check the pipeline's work.")
    c2.metric("Pipeline miscalibration", f"{pipeline_miscal}/{evaluable}", help="How often the pipeline said it was confident (4/5 or higher) but was actually wrong.")
    c3.metric("Judge miscalibration", f"{judge_miscal}/{evaluable}", help="How often the judge's review disagreed with the known-correct answer, in either direction.")

    st.dataframe(table_rows, use_container_width=True)

    st.caption(
        "Pipeline miscalibration = stated confidence >=4/5 but actually wrong. "
        "Judge miscalibration = judge's verdict disagreed with the known-correct answer."
    )


def render_eval_set():
    st.subheader("Eval Set — tracked failures over time")
    st.caption(
        "A confirmed failure shouldn't just be noticed once and forgotten — it belongs "
        "here, so you can re-check later whether a fix actually worked. Every confirmed "
        "failure (found automatically via a known-correct answer, or flagged manually in "
        "the Trace Explorer) lands in this list. Run `python eval_runner.py` to re-test "
        "them all against a fresh pipeline run."
    )

    cases = list_eval_cases()
    if not cases:
        st.info(
            "Nothing tracked yet. Run `python generate_eval_cases.py` to pull in any "
            "known failures already sitting in your run history, or open the Trace "
            "Explorer tab and use the 🚩 flag button on a step you disagree with."
        )
        return

    table_rows = []
    for row in cases:
        case = load_eval_case_by_id(row["eval_id"])
        if case is None:
            continue
        rate = case.resolution_rate
        table_rows.append({
            "eval_id": case.eval_id,
            "file": case.source_filename,
            "step": case.relevant_step,
            "category": case.failure_category,
            "origin": case.origin,
            "runs": len(case.run_history),
            "resolution rate": f"{rate*100:.0f}%" if rate is not None else "—",
            "latest": "resolved" if case.latest_status else ("still failing" if case.latest_status is False else "needs review"),
        })

    st.dataframe(table_rows, use_container_width=True)
    st.caption(
        "**origin**: `ground_truth` = caught automatically because we know the right "
        "answer; `manual_flag` = a human confirmed it.  **resolution rate**: the share "
        "of re-tests where the failure no longer happened — not just whether it worked once."
    )


def render_new_document():
    st.subheader("Run a new document through the pipeline")
    st.caption(
        "Paste any document text below and it'll go through all 4 pipeline steps "
        "live, right now — same code, same tracing, same everything as the sample "
        "documents. Good way to try this on something you made up on the spot."
    )

    example_choice = st.selectbox(
        "Start from a blank box, or load one of the built-in examples to edit:",
        ["(blank)"] + list(GROUND_TRUTH.keys()),
    )
    default_text = ""
    if example_choice != "(blank)":
        sample_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "sample_docs", example_choice
        )
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                default_text = f.read()

    filename = st.text_input("Give it a filename (just for labeling this run)", value="my_test_doc.txt")
    doc_text = st.text_area("Document text", value=default_text, height=220)

    if st.button("▶️ Run pipeline on this document", type="primary"):
        if not doc_text.strip():
            st.error("Paste something in first — there's nothing to process.")
        else:
            with st.spinner("Running intake → extraction → classification → summarization (calls your local LLM)..."):
                result = run_pipeline(doc_text, filename)
            st.success(f"Done. Trace ID: `{result.trace_id}` — find it in the Trace Explorer sidebar to inspect it.")

            if result.failed_at_step:
                st.error(
                    f"Pipeline stopped at **{result.failed_at_step}**: {result.error_message}\n\n"
                    "If this looks like a connection error, this feature needs Ollama "
                    "running locally, or an Anthropic API key configured — it won't "
                    "work on a hosted demo with no model behind it."
                )
            else:
                st.write("**Classification:**", result.classification.document_type.value,
                          f"(confidence {result.classification.classification_confidence:.0%}, "
                          f"ambiguous={result.classification.ambiguous})")
                st.write("**Summary:**", result.summarization.summary)
                if result.summarization.key_risk_flags:
                    st.write("**Risk flags (from the model):**", result.summarization.key_risk_flags)
                if result.summarization.verified_risk_flags:
                    st.error("**Risk flags (verified deterministically):** " + "; ".join(result.summarization.verified_risk_flags))

            st.caption("Want the full step-by-step breakdown and root-cause diagnosis? Switch to the Trace Explorer tab and select this run from the sidebar.")


st.title("🔍 Failure Forensics — Trace Explorer")

st.markdown(
    "This dashboard shows what happened each time an AI document-processing "
    "pipeline ran, and helps pinpoint exactly which step went wrong when it did."
)

with st.expander("ℹ️ New here? Read this first — a quick glossary"):
    st.markdown("""
**What is this pipeline actually doing?** Every document goes through 4 steps:
`intake` (read the file) → `extraction` (pull out names, dates, amounts) →
`classification` (decide what type of document it is) → `summarization`
(write a short summary and flag anything risky).

**Run / Trace** — one full pass of one document through all 4 steps.

**Span** — the record of what happened during ONE step of ONE run: what it
was given, what it produced, how long it took, and how confident it was.

**Confidence** — a 1-5 score for how sure a step was about its own output.
Important: confidence is the step's own self-assessment, not proof it was
actually right — a step can be very confident and still wrong (that's one
of the main things this tool exists to catch).

**🟢 🟡 🔴 colors** — green means a step scored well, yellow means it scored
itself low confidence, red means either it crashed or it's been identified
as the root cause of a real problem.

**The Judge** — a second AI call that reviews what a step produced and
scores whether it actually did a good job, independent of the step's own
self-reported confidence. Think of it as a reviewer checking someone else's
work — and like any reviewer, it can also be wrong sometimes (see the
Calibration tab).

**Ground truth** — for a handful of test documents, we already know the
correct answer ahead of time. That lets us check not just what the
pipeline *said*, but whether it was actually *right*.

**Root cause** — when something goes wrong across multiple steps, the root
cause is the *first* step where the problem actually started, since later
steps are often just inheriting an earlier mistake.

Want to try it yourself rather than just browsing past runs? The **Run New
Document** tab lets you paste in anything and watch it go through the
pipeline live.
    """)

tab1, tab2, tab3, tab4 = st.tabs(["Trace Explorer", "Calibration Overview", "Eval Set", "Run New Document"])
with tab1:
    render_trace_explorer()
with tab2:
    render_calibration_overview()
with tab3:
    render_eval_set()
with tab4:
    render_new_document()
