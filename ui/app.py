# ui/app.py
from __future__ import annotations
import os, time, json, requests, pandas as pd, streamlit as st
import ast

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
BACKEND = os.getenv("BACKEND", "http://localhost:8000")   # docker gives http://api:8000

# universal rerun helper (works on old / new Streamlit)
def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ---------- tiny HTTP helpers ------------------------------------- #
def fetch_status(job_id: str) -> dict:
    try:
        r = requests.get(f"{BACKEND}/jobs/{job_id}", timeout=10)
        return r.json() if r.status_code == 200 else {
            "status": "error", "logs": f"{r.status_code} {r.text[:200]}"}
    except Exception as e:
        return {"status": "error", "logs": str(e)}

def fetch_result(job_id: str) -> dict | None:
    try:
        r = requests.get(f"{BACKEND}/jobs/{job_id}/result", timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def fetch_jobs(status: str | None = "done") -> list[dict]:
    try:
        url = f"{BACKEND}/jobs" + (f"?status={status}" if status else "")
        return requests.get(url, timeout=10).json()
    except Exception:
        return []

# ------------------------------------------------------------------ #
# UI – inputs
# ------------------------------------------------------------------ #
st.title("🔎 Personal Research Guild")

col_topic, col_days, col_max = st.columns([3, 1, 1])
topic = col_topic.text_input("Topic", "ai safety")
days  = col_days.number_input("Days", 1, 30, 2, step=1)
max_p = col_max.number_input("Max papers", 5, 100, 25, step=5)

btn_run_col, btn_clear_col = st.columns(2)
with btn_run_col:
    run_btn = st.button("🚀 Run pipeline", use_container_width=True)
with btn_clear_col:
    clear_btn = st.button("🗑 Clear Data", use_container_width=True)

log_box = st.empty()

# ------------------------------------------------------------------ #
# Session keys
# ------------------------------------------------------------------ #
state = st.session_state
for key in ("job_id", "ready", "results"):
    state.setdefault(key, None)

# ------------------------------------------------------------------ #
# Clear-data button
# ------------------------------------------------------------------ #
if clear_btn:
    r = requests.post(f"{BACKEND}/admin/clear")
    if r.status_code == 204:
        st.success("Tables cleared.")
        for k in ("job_id", "ready", "results"):
            if k in state: state.pop(k)
        _rerun()
    else:
        st.error(f"Backend error: {r.status_code}")

# ------------------------------------------------------------------ #
# Run-pipeline button
# ------------------------------------------------------------------ #
if run_btn:
    payload = {"topic": topic, "days": int(days), "max_results": int(max_p)}
    r = requests.post(f"{BACKEND}/jobs", json=payload)
    if r.status_code == 202:
        state.job_id = r.json()["job_id"]
        state.ready  = None
        state.results = None
        _rerun()
    else:
        st.error(f"Backend error: {r.status_code}\n{r.text}")

# ------------------------------------------------------------------ #
# Polling / live logs
# ------------------------------------------------------------------ #
job_id = state.get("job_id")
if job_id and not state.results:
    status = fetch_status(job_id)
    st.text_area("Logs", status.get("logs", ""), height=200)
    st.info(f"Job `{job_id}` • status: **{status['status']}**")

    if status["status"] in ("running", "queued"):
        time.sleep(5)
        _rerun()

    elif status["status"] == "done":
        if not state.ready:
            state.ready = True      # first time we see done
            _rerun()
        if st.button("📂 View Results"):
            res = fetch_result(job_id)
            if res:
                state.results = res
                _rerun()

    elif status["status"] == "failed":
        st.error(status.get("error", "Unknown backend error"))

    st.stop()   # don’t show other sections while waiting / ready

# ------------------------------------------------------------------ #
# Past Jobs section
# ------------------------------------------------------------------ #
jobs_done = fetch_jobs()
if jobs_done:
    st.subheader("🗂 Past Jobs")
    for j in jobs_done:
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.markdown(f"`{j['id']}`  \n*{j['topic'][:40]}*")
        c2.write(j["status"])
        if c3.button("View Results", key=f"view-{j['id']}"):
            res = fetch_result(j["id"])
            if res:
                state.job_id  = j["id"]
                state.results = res
                state.ready   = True
                _rerun()
    st.divider()

# ------------------------------------------------------------------ #
# Render results if present
# ------------------------------------------------------------------ #
if state.results:
    res = state.results

    # ---------- Reading Plan ----------
    st.subheader("📅 Suggested Reading Queue")
    st.markdown(res["reading_plan"])

    # ---------- Trends ----------
    raw_trends = json.loads(res["trends_json"])

    # legacy snapshots: each element may be a string that looks like a Python dict
    parsed = []
    for item in raw_trends:
        if isinstance(item, str):
            try:
                parsed.append(ast.literal_eval(item))   # "{'trend_label': ...}" → dict
            except Exception:
                continue                                # skip if it still can’t parse
        elif isinstance(item, dict):
            parsed.append(item)

    tr_df = pd.DataFrame(parsed)

    papers_df = pd.DataFrame(json.loads(res["papers_json"]))
    for c in ("score_novelty", "score_method", "score_relevance"):
        if c in papers_df.columns:
            papers_df[c] = pd.to_numeric(papers_df[c], errors="coerce")

    if not tr_df.empty and not papers_df.empty:
        for _, tr in tr_df.iterrows():
            label  = tr.get("trend_label") or tr.get("label") or "—"
            cnt    = int(tr.get("count", 0))
            growth = float(tr.get("growth", 0))
            ids_raw = tr.get("paper_ids", "[]")

            # paper_ids is stored as JSON string
            try:
                ids = json.loads(ids_raw) if isinstance(ids_raw, str) else ids_raw
            except Exception:
                ids = []
            with st.expander(f"{label} — {cnt} papers ({'+' if growth>=0 else ''}{growth*100:.0f} %)"):
                id_col = "id" if "id" in papers_df.columns else (
                        "paper_id" if "paper_id" in papers_df.columns else None)

                if id_col:
                    group = papers_df[papers_df[id_col].isin(ids)].set_index(id_col)
                    # re-order to match ids list, keeping only those found
                    group = group.loc[[i for i in ids if i in group.index]]
                else:
                    # extreme fallback: nothing matches
                    group = pd.DataFrame()
                for _, row in group.iterrows():
                    pid = row.name
                    if st.toggle(row.title, key=f"trend-{pid}"):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Novelty",     row.score_novelty   or "—")
                        c2.metric("Methodology", row.score_method    or "—")
                        c3.metric("Relevance",   row.score_relevance or "—")
                        st.markdown("**Summary**");  st.markdown(row.summary or "_No summary_")
                        st.markdown(f"[🔗 PDF]({row.pdf_url})")
                        if st.toggle("Raw JSON", key=f"raw-{pid}"):
                            st.json(row.dropna().to_dict())
                        st.markdown("---")
        st.divider()

    # ---------- Papers quick table ----------
    if not papers_df.empty:
        st.subheader("📄 All papers")

        # choose safe columns that actually exist
        cols = [c for c in ("title", "created_at") if c in papers_df.columns]
        if not cols:                          # fallback if both missing
            cols = papers_df.columns[:2]      # show first two columns

        st.dataframe(papers_df[cols])