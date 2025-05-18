from __future__ import annotations
import sys, os, queue, threading, time, json, sqlite3, pandas as pd, streamlit as st

# make project root importable
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from guild_graph import run_pipeline
from services.db_utils import clear_all_tables

DB = "guild.db"

# ---------- Streamlit-version-safe rerun ---------- #
def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ---------- cached DB loaders ---------- #
@st.cache_data(show_spinner=False)
def load_papers() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM papers ORDER BY created_at DESC", conn)
    conn.close()
    for col in ["score_novelty", "score_method", "score_relevance"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(show_spinner=False)
def load_trends() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    tdf = pd.read_sql("SELECT * FROM trends ORDER BY id", conn)
    conn.close()
    return tdf

@st.cache_data(show_spinner=False)
def load_plan() -> str | None:
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT plan_text FROM plans ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else None

# ---------- UI: inputs ---------- #
st.title("🔎 Personal Research Guild")

row1_col_topic, row1_col_days, row1_col_max = st.columns([3, 2, 2])
with row1_col_topic:
    topic = st.text_input("Topic", value="ai safety")
with row1_col_days:
    days = st.number_input("Look-back Days", 1, 30, 2, step=1)
with row1_col_max:
    max_papers = st.number_input("Max Papers", 5, 100, 25, step=5)

row2_run, row2_clear = st.columns(2)
with row2_run:
    run_btn = st.button("🚀 Run pipeline")
with row2_clear:
    clear_btn = st.button("🗑 Clear Data")

log_box = st.empty()

# ---------- session flags ---------- #
if "busy" not in st.session_state:
    st.session_state.busy = False
if "log_q" not in st.session_state:
    st.session_state.log_q = queue.Queue()
if "worker" not in st.session_state:
    st.session_state.worker = None  # type: ignore

# ---------- CLEAR DATA ---------- #
if clear_btn and not st.session_state.busy:
    clear_all_tables()
    load_papers.clear(); load_trends.clear(); load_plan.clear()
    _rerun()

# ---------- START PIPELINE ---------- #
if run_btn and not st.session_state.busy:
    st.session_state.busy = True
    st.session_state.log_q = queue.Queue()

    thread = threading.Thread(
        target=run_pipeline,
        args=(topic, st.session_state.log_q),
        kwargs=dict(days=int(days), max_results=int(max_papers)),
        daemon=True,
    )
    thread.start()
    st.session_state.worker = thread

# ---------- BUSY LOOP ---------- #
if st.session_state.busy:
    logs, done = [], False
    while not st.session_state.log_q.empty():
        msg = st.session_state.log_q.get_nowait()
        if msg == "__DONE__":
            done = True
        else:
            logs.append(msg)

    st.warning("⏳ Pipeline running…")
    if logs:
        log_box.code("\n".join(logs[-15:]))

    if done:
        # 🆕 1. wait for the thread to finish disk I/O
        if st.session_state.worker:
            st.session_state.worker.join(timeout=2)

        # 🆕 2. mark pipeline finished
        st.session_state.busy = False
        st.session_state.worker = None

        # 🆕 3. clear Streamlit caches so new DB rows are fetched
        load_papers.clear(); load_trends.clear(); load_plan.clear()

        # 🆕 4. hard rerun the script -> idle view renders new data
        _rerun()

    time.sleep(0.5)

# ---------- IDLE VIEW ---------- #
if not st.session_state.busy:
    log_box.empty()

    # Suggested Reading Plan
    plan = load_plan()
    if plan:
        st.subheader("📅 Suggested Reading Queue")
        st.markdown(plan, unsafe_allow_html=True)
        st.divider()

    # Trending clusters
    trends_df = load_trends()
    if not trends_df.empty:
        st.subheader("🔥 Trending topics (last 7 days)")
        papers_df = load_papers()
        trends_df = trends_df.sort_values("growth", ascending=False)

        for _, tr in trends_df.iterrows():
            label, cnt, growth = tr["trend_label"], int(tr["count"]), tr["growth"]
            sign = "+" if growth >= 0 else ""
            ids  = json.loads(tr["paper_ids"])

            with st.expander(f"{label} — {cnt} papers ({sign}{growth*100:.0f} %)"):
                group = papers_df[papers_df.id.isin(ids)].set_index("id").loc[ids]

                for _, row in group.iterrows():
                    pid   = row.name
                    title = row["title"]

                    if st.toggle(title, key=f"trend-{pid}"):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Novelty",     row["score_novelty"]   or "—")
                        c2.metric("Methodology", row["score_method"]    or "—")
                        c3.metric("Relevance",   row["score_relevance"] or "—")

                        st.markdown("**Summary**")
                        st.markdown(row["summary"] or "_No summary_")

                        st.markdown(f"[🔗 PDF]({row['pdf_url']})")

                        st.markdown("**Critique**")
                        st.markdown(row["critique"] or "_No critique_")

                        if st.toggle("Raw JSON", key=f"raw-{pid}"):
                            st.json(row.dropna().to_dict())

                        st.markdown("---")
        st.divider()

    # All papers quick table
    st.subheader("🗂 All papers")
    st.dataframe(load_papers()[["title", "created_at"]])
