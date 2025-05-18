"""
services/db_utils.py
--------------------
Utility helpers that act **only on the database layer**.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "guild.db"

def clear_all_tables() -> None:
    """Delete every row in papers, trends, and plans; keep the schema intact."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM papers;")
        conn.execute("DELETE FROM trends;")
        conn.execute("DELETE FROM plans;")
        conn.commit()
