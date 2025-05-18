"""
Streamlit dashboard for the Personal Research Guild
---------------------------------------------------
* Lists all papers in `guild.db`
* Lets you filter by title / date / min-scores
* Expands each row to reveal:
    – Summary (bullets)
    – Critique paragraph
    – Three 0-10 score “metric” widgets
Run:
    streamlit run ui/app.py
"""

from __future__ import annotations
import json, sqlite3, pandas as pd, streamlit as st
from datetime import datetime

DB = "guild.db"

# ------------------------------------------------------------------ #
# Helpers (cached)                                                   #
# ------------------------------------------------------------------ #
@st.cache_data(show_spinner=False)
def load_papers() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    df = pd.read_sql(
        """SELECT id, title, summary, pdf_url,
                  IFNULL(score_novelty,'')   AS novelty,
                  IFNULL(score_method,'')    AS method,
                  IFNULL(score_relevance,'') AS relevance,
                  IFNULL(critique,'')        AS critique
           FROM papers ORDER BY created_at DESC""",
        conn,
    )
    conn.close()
    for c in ["novelty", "method", "relevance"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_trends() -> pd.DataFrame:
    conn = sqlite3.connect(DB)
    tdf = pd.read_sql(
        "SELECT trend_label, count, growth, paper_ids FROM trends ORDER BY id",
        conn,
    )
    conn.close()
    return tdf

@st.cache_data(show_spinner=False)
def load_plan() -> str | None:
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT plan_text FROM plans ORDER BY id DESC LIMIT 1;").fetchone()
    conn.close()
    return row[0] if row else None

# ------------------------------------------------------------------ #
# Title + Refresh                                                    #
# ------------------------------------------------------------------ #
st.title("📚 Personal Research Guild")
if "last_loaded" not in st.session_state:
    st.session_state.last_loaded = datetime.utcnow()

if st.sidebar.button("↻ Refresh data"):
    load_papers.clear()   # clear Streamlit cache
    load_trends.clear()
    st.session_state.last_loaded = datetime.utcnow()

papers_df = load_papers()
trends_df = load_trends()

st.caption(f"*Data last loaded: {st.session_state.last_loaded.isoformat(timespec='seconds')}*")

# ------------------------------------------------------------------ #
# 🔥 Trending topics                                                 #
# ------------------------------------------------------------------ #
if not trends_df.empty:
    st.subheader("🔥 Trending topics (last 7 days)")

    # order by growth descending
    trends_df = trends_df.sort_values("growth", ascending=False, ignore_index=True)

    for _, tr in trends_df.iterrows():
        label   = tr["trend_label"]
        cnt     = int(tr["count"])
        growth  = tr["growth"]
        sign    = "+" if growth >= 0 else ""
        paper_ids = json.loads(tr["paper_ids"])

        with st.expander(f"{label} — {cnt} papers  ({sign}{growth*100:.0f} %)", expanded=False):
            # newest-first order was saved by TrendAnalyzer
            subset = papers_df[papers_df["id"].isin(paper_ids)].set_index("id").loc[paper_ids]

            for _, row in subset.iterrows():
                # TOP-LEVEL TOGGLE – avoids nested expanders
                paper_id = row.name 
                if st.toggle(row["title"], key=f"t-{paper_id}"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Novelty",    row.novelty if pd.notna(row.novelty) else "—")
                    c2.metric("Methodology",row.method  if pd.notna(row.method)  else "—")
                    c3.metric("Relevance",  row.relevance if pd.notna(row.relevance) else "—")

                    st.markdown("**Summary**")
                    st.markdown(row.summary or "_(No summary yet)_")

                    st.markdown(f"[🔗 Open paper / PDF]({row.pdf_url})") 

                    st.markdown("**Critique**")
                    st.markdown(row.critique or "_(No critique yet)_")

                    if st.toggle("Raw JSON", key=f"raw-{paper_id}"):
                        st.json(row.dropna().to_dict())

                    st.markdown("---")

    st.divider()

# ------------------------------------------------------------------ #
#   Planner Block After Trends                                       #
# ------------------------------------------------------------------ #

plan_text = load_plan()
if plan_text:
    st.subheader("📅 Suggested Reading Queue")
    st.markdown(plan_text, unsafe_allow_html=True)
    st.divider()

# ------------------------------------------------------------------ #
# 🔎  All papers (filterable)                                        #
# ------------------------------------------------------------------ #
with st.sidebar:
    st.header("Filters – All Papers")
    title_q  = st.text_input("Title contains")
    min_nov  = st.slider("Min Novelty",    0, 10, 0)
    min_meth = st.slider("Min Methodology",0, 10, 0)
    min_rel  = st.slider("Min Relevance",  0, 10, 0)

mask = (
    (papers_df["title"].str.contains(title_q, case=False, regex=False) if title_q else True)
    & (papers_df["novelty"].fillna(10)   >= min_nov)
    & (papers_df["method"].fillna(10)    >= min_meth)
    & (papers_df["relevance"].fillna(10) >= min_rel)
)
filtered_df = papers_df[mask]
st.subheader(f"🗂 All Papers  —  {len(filtered_df)} shown / {len(papers_df)} total")

for _, row in filtered_df.iterrows():
    paper_id = row["id"]
    if st.toggle(row["title"], key=f"all-{paper_id}"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Novelty",    row.novelty if pd.notna(row.novelty) else "—")
        c2.metric("Methodology",row.method  if pd.notna(row.method)  else "—")
        c3.metric("Relevance",  row.relevance if pd.notna(row.relevance) else "—")

        st.markdown("**Summary**")
        st.markdown(row.summary or "_(No summary yet)_")

        st.markdown(f"[🔗 Open paper / PDF]({row.pdf_url})") 

        st.markdown("**Critique**")
        st.markdown(row.critique or "_(No critique yet)_")

        if st.toggle("Raw JSON", key=f"all-raw-{paper_id}"):
            st.json(row.dropna().to_dict())

        st.markdown("---")

# ------------------------------------------------------------------ #
st.info(
    "**Tip:** run `python guild_graph.py` (or the Docker service) to fetch → "
    "summarise → critique → update trends. Then click **Refresh data**."
)