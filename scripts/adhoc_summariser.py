"""Ad‑hoc utility: summarise any papers in the DB whose `summary` is still blank.

Usage
-----
Activate your virtualenv (or run inside Docker Compose shell) then:

    python scripts/adhoc_summariser.py [--batch 5]

By default it processes up to 10 unsummarised papers in one run.  Re‑run the
script until it prints "No unsummarised papers left".

The script prints a short preview (title + first 100 chars) for each new
summary so you can visually confirm it worked.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

# --------------------------------------------------------------------- #
# Ensure project root is on sys.path
# --------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------- #
# Now we can import project modules
# --------------------------------------------------------------------- #
from dotenv import load_dotenv  # type: ignore
from sqlalchemy import select, update  # type: ignore

from agents.summariser import SummariserAgent
from services.storage import engine, papers

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def fetch_unsummarised(limit: int) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(papers.c.id, papers.c.title, papers.c.pdf_url)
            .where(papers.c.summary == "")
            .where(papers.c.pdf_url != "")
            .limit(limit)
        ).fetchall()
    return [
        {"paper_id": r.id, "title": r.title, "pdf_url": r.pdf_url} for r in rows
    ]


def persist(paper_id: str, summary: str):
    with engine.begin() as conn:
        conn.execute(update(papers).where(papers.c.id == paper_id).values(summary=summary))


def main(batch: int):
    work = fetch_unsummarised(batch)
    if not work:
        logger.info("No unsummarised papers left – nothing to do ✔")
        return

    logger.info("Summarising %d papers…", len(work))
    summariser = SummariserAgent()
    summarised, _ = summariser.run(work, {})

    for paper in summarised:
        persist(paper["paper_id"], paper["summary"])
        preview = textwrap.shorten(paper["summary"], width=100)
        logger.info("• %s → %s", paper["title"], preview)

    logger.info("Done. Run again to process further batches if needed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ad-hoc summarise unsummarised papers")
    parser.add_argument("--batch", type=int, default=10, help="Max papers per run (default 10)")
    args = parser.parse_args()
    main(args.batch)
