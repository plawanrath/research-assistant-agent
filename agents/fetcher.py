"""FetcherAgent – pulls new papers from arXiv and Semantic Scholar.

Usage pattern (LangGraph):
>>> from agents.fetcher import FetcherAgent
>>> fetcher = FetcherAgent(topic="ai safety", since_days=2)
>>> new_papers, new_state = fetcher.run(message=None, state={})

The agent:
* Queries arXiv and Semantic Scholar REST APIs.
* De‑duplicates by DOI / arXiv ID so we don’t re‑process known papers.
* Persists basic metadata + raw PDF URL in SQLite via services.storage.
* Returns a list of work units for the downstream Summariser agent.

Environment variables (set in your docker‑compose.yml):
    OPENAI_API_KEY               – for later stages (not used here)
    SEMANTIC_SCHOLAR_API_KEY     – optional, higher S2 quota.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import requests
from requests.exceptions import HTTPError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from services.storage import engine, papers  # type: ignore

logger = logging.getLogger(__name__)

# ------------------------------- Constants ------------------------------ #
ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)

# ---------------------------- Helper functions -------------------------- #

def _existing_ids() -> Tuple[set[str], set[str]]:
    """Return sets of arXiv IDs and DOIs already in the DB."""
    with engine.connect() as conn:
        rows = conn.execute(select(papers.c.id)).fetchall()
    arx, dois = set(), set()
    for (pid,) in rows:
        (arx if pid.startswith("arxiv:" ) else dois).add(pid)
    return arx, dois


# ------------------------------ Agent class ----------------------------- #
class FetcherAgent:
    """LangGraph‑compatible agent that fetches new papers."""

    def __init__(self, topic: str, *, since_days: int = 3, max_results: int = 50):
        self.topic = topic
        self.since_days = since_days
        self.max_results = max_results
        self.s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

    # ------------------------------------------------------------------ #
    def run(self, _msg: Any, state: Dict[str, Any]):
        arxiv_items = self._fetch_arxiv()
        s2_items = self._fetch_semantic_scholar()
        combined = {i["paper_id"]: i for i in arxiv_items}
        for it in s2_items:
            combined.setdefault(it["paper_id"], it)
        new_items = list(combined.values())
        self._persist(new_items)
        return new_items, {**state, "last_fetch_ts": time.time()}

    # ---------------- arXiv ---------------- #
    def _date_range(self):
        end = datetime.utcnow()
        start = end - timedelta(days=self.since_days)
        return start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")

    def _fetch_arxiv(self):
        start_date, end_date = self._date_range()
        query = f"all:{self.topic} AND submittedDate:[{start_date} TO {end_date}]"
        params = {
            "search_query": query,
            "start": 0,
            "max_results": self.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = requests.get(ARXIV_API, params=params, timeout=30)
        resp.raise_for_status()
        entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.S)
        arxiv_done, _ = _existing_ids()
        out: List[Dict[str, Any]] = []
        for ent in entries:
            m = re.search(r"<id>http://arxiv.org/abs/(.*?)</id>", ent)
            if not m:
                continue
            aid = m.group(1)
            if aid in arxiv_done:
                continue
            title = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", ent, re.S).group(1).strip())
            doi_tag = re.search(r"<arxiv:doi>(.*?)</arxiv:doi>", ent)
            doi = doi_tag.group(1) if doi_tag else None
            out.append({
                "paper_id": f"arxiv:{aid}",
                "title": title,
                "doi": doi,
                "source": "arXiv",
                "pdf_url": f"https://arxiv.org/pdf/{aid}.pdf",
            })
        logger.info("FetcherAgent: %d new arXiv papers", len(out))
        return out

    # ---------------- Semantic Scholar ---------------- #
    def _fetch_semantic_scholar(self):
        headers = {"x-api-key": self.s2_key} if self.s2_key else {}
        params = {
            "query": self.topic,
            "limit": self.max_results,
            "offset": 0,
            "fields": "title,externalIds,url,year,isOpenAccess,openAccessPdf",
        }
        try:
            resp = requests.get(S2_API, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
        except HTTPError as err:
            logger.warning("S2 fetch failed (%s)", err)
            return []
        data = resp.json().get("data", [])
        _, dois_done = _existing_ids()
        results: List[Dict[str, Any]] = []
        for item in data:
            doi = (item.get("externalIds") or {}).get("DOI")
            if not doi or doi in dois_done or not _DOI_RE.match(doi):
                continue
            pdf_url = (item.get("openAccessPdf") or {}).get("url") or item.get("url", "")
            results.append({
                "paper_id": doi,
                "title": item.get("title", ""),
                "doi": doi,
                "source": "Semantic Scholar",
                "pdf_url": pdf_url,
            })
        logger.info("FetcherAgent: %d new S2 papers", len(results))
        return results

    # ---------------- Persistence ---------------- #
    def _persist(self, items: List[Dict[str, Any]]):
        if not items:
            return
        with engine.begin() as conn:
            for it in items:
                stmt = (
                    sqlite_insert(papers)
                    .values(
                        id=it["paper_id"],
                        title=it["title"],
                        summary="",
                        pdf_url=it["pdf_url"],
                        embedding=json.dumps([]),
                    )
                    .prefix_with("OR IGNORE")
                )
                conn.execute(stmt)
        logger.info("FetcherAgent: attempted insert %d rows (duplicates ignored)", len(items))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    f = FetcherAgent(topic="ai safety", since_days=1, max_results=10)
    new, _ = f.run(None, {})
    print(json.dumps(new[:3], indent=2))