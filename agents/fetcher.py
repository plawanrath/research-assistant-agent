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
from typing import Dict, List, Tuple, Any

import requests
from sqlalchemy import select, insert

# Local service
from services.storage import engine, papers  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def _existing_ids() -> Tuple[set[str], set[str]]:
    """Return two sets: arxiv_ids and dois already in DB."""
    with engine.connect() as conn:
        res = conn.execute(select(papers.c.id)).fetchall()
    arxiv_ids, dois = set(), set()
    for (pid,) in res:
        if pid.startswith("arxiv:"):
            arxiv_ids.add(pid)
        else:
            dois.add(pid)
    return arxiv_ids, dois


class FetcherAgent:
    """Simple callable class that fits the LangGraph “node” protocol."""

    def __init__(self, topic: str, since_days: int = 3, max_results: int = 50):
        self.topic = topic
        self.since_days = since_days
        self.max_results = max_results
        self.s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

    # ---- Public API expected by LangGraph ---- #
    def run(self, message: Any, state: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Fetch new papers → return list[dict] for downstream agents."""
        logger.info("FetcherAgent: querying sources…")
        arxiv_items = self._fetch_arxiv()
        s2_items = self._fetch_semantic_scholar()

        # Merge + dedup
        combined: Dict[str, Dict[str, Any]] = {item["paper_id"]: item for item in arxiv_items}
        for it in s2_items:
            combined.setdefault(it["paper_id"], it)

        new_items = list(combined.values())
        logger.info(f"FetcherAgent: {len(new_items)} new papers fetched.")

        self._persist(new_items)

        # Update agent state ➜ last_run timestamp
        new_state = {**state, "last_fetch_ts": time.time()}
        return new_items, new_state

    # ---- Private helpers ---- #
    def _date_range(self) -> Tuple[str, str]:
        end = datetime.utcnow()
        start = end - timedelta(days=self.since_days)
        return start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")

    def _fetch_arxiv(self) -> List[Dict[str, Any]]:
        start_date, end_date = self._date_range()
        query = f"all:{self.topic} AND submittedDate:[{start_date} TO {end_date}]"
        params = {
            "search_query": query,
            "start": 0,
            "max_results": self.max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        logger.debug(f"arXiv params: {params}")
        resp = requests.get(ARXIV_API, params=params, timeout=30)
        resp.raise_for_status()
        # arXiv returns Atom XML; parse via regex for speed
        entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.S)
        arxiv_ids, dois = _existing_ids()
        results: List[Dict[str, Any]] = []
        for entry in entries:
            id_match = re.search(r"<id>http://arxiv.org/abs/(.*?)</id>", entry)
            if not id_match:
                continue
            aid = id_match.group(1)
            if aid in arxiv_ids:
                continue  # already processed
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            title_text = re.sub(r"\s+", " ", title.group(1).strip()) if title else ""
            pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
            doi_match = re.search(r"<arxiv:doi>(.*?)</arxiv:doi>", entry)
            doi = doi_match.group(1) if doi_match else None
            results.append({
                "paper_id": f"arxiv:{aid}",
                "title": title_text,
                "doi": doi,
                "source": "arXiv",
                "pdf_url": pdf_url,
            })
        return results

    def _fetch_semantic_scholar(self) -> List[Dict[str, Any]]:
        arxiv_ids, dois = _existing_ids()
        headers = {"x-api-key": self.s2_key} if self.s2_key else {}
        params = {
            "query": self.topic,
            "limit": self.max_results,
            "fields": "title,authors,doi,url,year",
        }
        resp = requests.get(S2_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        results: List[Dict[str, Any]] = []
        for item in data:
            doi = item.get("doi")
            if not doi:
                continue
            if doi in dois:
                continue
            # Semantic Scholar doesn’t store PDFs; use url if PDF
            pdf_url = item.get("url", "")
            results.append({
                "paper_id": doi,
                "title": item.get("title", ""),
                "doi": doi,
                "source": "Semantic Scholar",
                "pdf_url": pdf_url,
            })
        return results

    def _persist(self, items: List[Dict[str, Any]]):
        if not items:
            return
        with engine.begin() as conn:
            for it in items:
                conn.execute(insert(papers).values(
                    id=it["paper_id"],
                    title=it["title"],
                    summary="",  # placeholder for next agent
                    embedding=json.dumps([]),
                ))
        logger.info(f"FetcherAgent: persisted {len(items)} rows to DB.")


# Quick CLI test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetcher = FetcherAgent(topic="ai safety", since_days=1, max_results=10)
    papers_out, _ = fetcher.run(None, {})
    print(json.dumps(papers_out, indent=2)[:1000])
