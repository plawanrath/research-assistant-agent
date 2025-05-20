from __future__ import annotations
import os, time, json, ast, requests, pandas as pd, streamlit as st

# ── Page metadata (must be the first Streamlit call) ────────────
st.set_page_config(
    page_title="Research Assistant",   # what shows in the browser tab
    page_icon="🔎",                    # optional favicon / emoji
    layout="wide"                      # optional – keeps your current layout
)

# ───────────────────────── Config ────────────────────────── #
BACKEND = os.getenv("BACKEND", "http://localhost:8000")     # docker ⇒ http://api:8000
from services.auth import verify                            # bcrypt password check

# ---------- helper: universal rerun ---------- #
_rerun = (st.rerun if hasattr(st, "rerun") else st.experimental_rerun)

# ---------- CSS for centred login card ---------- #
st.markdown(
    """
    <style>
      html, body, .main {height:100%;}
      div.login-card {border:1px solid #ddd; padding:2rem 3rem; border-radius:10px;
                      box-shadow:2px 2px 6px rgba(0,0,0,0.05); width:340px;
                      margin:1.5rem auto;}
      button.logout {background:#f44336;color:#fff;border:none;padding:0.35rem 0.9rem;
                     border-radius:5px;font-size:0.85rem;cursor:pointer;}
      p.hint {font-size:0.85rem;color:#666;margin-top:0.8rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ───────────────────────── Session flags ─────── #
state = st.session_state
state.setdefault("logged_in", False)
for k in ("job_id", "ready", "results"):
    state.setdefault(k, None)

# ───────────────────────── Login gate ─────────── #
if not state.logged_in:
    st.markdown("## Research Assistant Login", unsafe_allow_html=True)
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login", use_container_width=True):
        if verify(u, p):
            state.logged_in = True
            _rerun()
        else:
            st.error("Login failed – wrong credentials.")

    # extra helper lines
    st.markdown(
        """
        <p class="hint">For access please email <strong>plawanrath@gmail.com</strong></p>
        <p class="hint">
          The agent is available open-source in
          <a href="https://github.com/plawanrath/research-assistant-agent.git" target="_blank">
            this&nbsp;repo
          </a>.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()
    st.stop()      # 🚧 nothing below until logged-in

# ───────────────────────── Logout top-left ──────────────────────── #
log_col, _ = st.columns([0.15, 0.85])
if log_col.button("Logout ⏏", key="logout", type="secondary"):
    for k in list(state.keys()):
        if k != "logged_in":
            state.pop(k)
    state.logged_in = False
    _rerun()

# ───────────────────────── Main App ───────────────────── #
st.title("🔎 Personal Research Guild")

# ---------- Input controls ---------- #
col_topic, col_days, col_max = st.columns([3, 1, 1])
topic = col_topic.text_input("Topic", "ai safety")
days  = col_days.number_input("Days", 1, 30, 2, step=1)
max_p = col_max.number_input("Max papers", 5, 100, 25, step=5)

btn_run_col, btn_clear_col = st.columns(2)
run_btn   = btn_run_col.button("🚀 Run pipeline", use_container_width=True)
clear_btn = btn_clear_col.button("🗑 Clear Data", use_container_width=True)

log_box = st.empty()

# ---------- tiny HTTP helpers ------------------- #
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

# ---------- Clear Data -------------------------- #
if clear_btn:
    resp = requests.post(f"{BACKEND}/admin/clear")
    if resp.status_code == 204:
        st.success("Tables cleared.")
        for k in ("job_id", "ready", "results"):
            state.pop(k, None)
        _rerun()
    else:
        st.error(f"Backend error: {resp.status_code}")

# ---------- Run pipeline ------------------------ #
if run_btn:
    payload = {"topic": topic, "days": int(days), "max_results": int(max_p)}
    resp = requests.post(f"{BACKEND}/jobs", json=payload)
    if resp.status_code == 202:
        state.job_id, state.ready, state.results = resp.json()["job_id"], None, None
        _rerun()
    else:
        st.error(f"Backend error: {resp.status_code}\n{resp.text}")

# ---------- Polling / live logs ----------------- #
if state.job_id and not state.results:
    status = fetch_status(state.job_id)
    st.text_area("Logs", status.get("logs", ""), height=200)
    st.info(f"Job `{state.job_id}` • status: **{status['status']}**")

    if status["status"] in ("running", "queued"):
        time.sleep(5); _rerun()
    elif status["status"] == "done":
        if not state.ready: state.ready = True; _rerun()
        if st.button("📂 View Results"):
            if (res := fetch_result(state.job_id)):
                state.results = res; _rerun()
    elif status["status"] == "failed":
        st.error(status.get("error", "Unknown backend error"))
    st.stop()

# ---------- Past Jobs --------------------------- #
if (jobs := fetch_jobs()):
    st.subheader("🗂 Past Jobs")
    for j in jobs:
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.markdown(f"`{j['id']}`  \n*{j['topic'][:40]}*")
        c2.write(j["status"])
        if c3.button("View Results", key=f"view-{j['id']}"):
            if (res := fetch_result(j["id"])):
                state.job_id, state.results, state.ready = j["id"], res, True
                _rerun()
    st.divider()

# ---------- Render results ---------------------- #
if state.results:
    res = state.results

    st.subheader("📅 Suggested Reading Queue")
    st.markdown(res["reading_plan"])

    # Trends
    trends_raw = json.loads(res["trends_json"])
    trends = [ast.literal_eval(x) if isinstance(x,str) else x for x in trends_raw]
    tr_df = pd.DataFrame(trends)

    papers_df = pd.DataFrame(json.loads(res["papers_json"]))
    for c in ("score_novelty","score_method","score_relevance"):
        if c in papers_df.columns: papers_df[c] = pd.to_numeric(papers_df[c], errors="coerce")

    if not tr_df.empty and not papers_df.empty:
        st.subheader("🔥 Trending topics (last 7 days)")
        for _, tr in tr_df.iterrows():
            label  = tr.get("trend_label") or tr.get("label") or "—"
            cnt    = int(tr.get("count",0))
            growth = float(tr.get("growth",0))
            ids    = json.loads(tr.get("paper_ids","[]"))
            with st.expander(f"{label} — {cnt} papers ({'+' if growth>=0 else ''}{growth*100:.0f} %)"):
                id_col = next((c for c in ("id","paper_id") if c in papers_df.columns), None)
                grp = papers_df[papers_df[id_col].isin(ids)].set_index(id_col) if id_col else pd.DataFrame()
                grp = grp.loc[[i for i in ids if i in grp.index]]
                for _, row in grp.iterrows():
                    pid = row.name
                    if st.toggle(row.title, key=f"trend-{pid}"):
                        c1,c2,c3 = st.columns(3)
                        c1.metric("Novelty", row.score_novelty or "—")
                        c2.metric("Methodology", row.score_method or "—")
                        c3.metric("Relevance", row.score_relevance or "—")
                        st.markdown("**Summary**"); st.markdown(row.summary or "_No summary_")
                        st.markdown(f"[🔗 PDF]({row.pdf_url})")
                        if st.toggle("Raw JSON", key=f"raw-{pid}"): st.json(row.dropna().to_dict())
                        st.markdown("---")
        st.divider()

    # Future Improvements
    if "ideas_json" in res:
        ideas_df = pd.DataFrame(json.loads(res["ideas_json"]))
        if not ideas_df.empty and not papers_df.empty:
            st.subheader("🔮 Future Improvements")
            id_col = next((c for c in ("id","paper_id") if c in papers_df.columns), None)
            merged = ideas_df.merge(
                papers_df[[id_col,"title"]], left_on="paper_id", right_on=id_col, how="left"
            ) if id_col else ideas_df
            merged["title"].fillna(merged["paper_id"], inplace=True)
            for pid, grp in merged.groupby("paper_id"):
                with st.expander(grp["title"].iloc[0] or pid):
                    for _, row in grp.sort_values("created_at", ascending=False).iterrows():
                        st.markdown(row["ideas"])
                        st.caption(row.get("created_at","")[:19])
            st.divider()

    # Papers quick table
    if not papers_df.empty:
        st.subheader("📄 All papers")
        cols = [c for c in ("title","created_at") if c in papers_df.columns] or papers_df.columns[:2]
        st.dataframe(papers_df[cols])