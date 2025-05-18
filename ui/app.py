from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Load secrets from .env so Streamlit picks up API keys if needed later
load_dotenv()

DB_PATH = Path(__file__).parent.parent / "guild.db"

st.set_page_config(page_title="Research Guild", layout="wide")

st.title("📚 Personal Research Guild – Summaries")

if not DB_PATH.exists():
    st.warning("Database not found – run guild_graph.py first to create summaries.")
    st.stop()

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Search/filter sidebar
with st.sidebar:
    st.header("Filters")
    search_term = st.text_input("Search title contains…", "")
    only_summarised = st.checkbox("Show only summarised", value=True)

query = "SELECT id, title, summary FROM papers"
where_clauses = []
if search_term:
    where_clauses.append("title LIKE ?")
if only_summarised:
    where_clauses.append("summary != ''")
if where_clauses:
    query += " WHERE " + " AND ".join(where_clauses)
query += " ORDER BY rowid DESC LIMIT 500"

params = [f"%{search_term}%"] if search_term else []
rows = cursor.execute(query, params).fetchall()

st.write(f"Found **{len(rows)}** papers")

for pid, title, summary in rows:
    with st.expander(title, expanded=False):
        st.markdown(summary or "_No summary generated yet_")
        st.caption(pid)

conn.close()