"""SummariserAgent – generates concise summaries for papers fetched by FetcherAgent.

Highlights
----------
* Downloads PDF (or HTML fallback) for each paper.
* Extracts text via **PyPDF2** (for small-ish PDFs) or HTTP fallback if Semantic
  Scholar provides a PDF‐direct URL.
* Chunks text into ~3 000‑token slices, summarises with OpenAI GPT‑4 Turbo using
  map‑reduce (chunk summary → merge summary).
* Saves the final summary into SQLite (`services.storage`) in the same row so
  downstream agents (Critic, Trend) can retrieve it quickly.

Env variables
-------------
* `OPENAI_API_KEY` – required.
* `OPENAI_MODEL`   – override model name (default: "gpt-4o-mini").
* `MAX_TOKENS`     – per‑chunk budget (default: 3 000).
"""

from __future__ import annotations

import io
import logging
import os
import re
import textwrap
from typing import Any, Dict, List, Optional

import openai
import requests
from PyPDF2 import PdfReader
from sqlalchemy import update

from services.storage import engine, papers  # type: ignore

logger = logging.getLogger(__name__)

# --------------------------- Config & helpers --------------------------- #
_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_MAX_TOKENS = int(os.getenv("MAX_TOKENS", "3000"))
CHUNK_SIZE_CHARS = 12_000  # rough char heuristic ≈ 3k tokens
S2_API = "https://api.semanticscholar.org/graph/v1/paper/"

openai.api_key = os.getenv("OPENAI_API_KEY")


# ---------------------------- Core functions --------------------------- #

def _download_pdf(url: str) -> bytes | None:
    """Return PDF bytes or None on error (adds UA header to avoid 403)."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            logger.debug("Response from %s is not a PDF", url)
            return None
        return resp.content
    except Exception as e:
        logger.warning("Failed to download %s (%s)", url, e)
        return None


def _extract_text(pdf_bytes: bytes) -> Optional[str]:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:
        logger.debug("PDF load error: %s", e)
        return None
    parts = []
    for p in reader.pages:
        try:
            parts.append(p.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts) if parts else None


def _chunk_text(text: str, chunk_chars: int = CHUNK_SIZE_CHARS) -> List[str]:
    paras = re.split(r"\n{2,}", text)
    chunks, buf, buf_len = [], [], 0
    for para in paras:
        para = para.strip()
        if not para:
            continue
        if buf_len + len(para) > chunk_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, buf_len = [], 0
        buf.append(para)
        buf_len += len(para)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _openai_summarise(text: str, model: str = _OPENAI_MODEL) -> str:
    sys_prompt = (
        "You are an expert research assistant. Summarise the following section "
        "of an academic paper in 3–4 bullet points (plain English, max 120 words)."
    )
    resp = openai.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
        max_tokens=256,
    )
    return resp.choices[0].message.content.strip()


def _map_reduce_summary(chunks: List[str]) -> str:
    if not chunks:
        return "(no text extracted)"
    intermediate = [_openai_summarise(ch) for ch in chunks]
    merged = _openai_summarise(
        "Combine these bullet‑point summaries into an overall 5‑line abstract:\n\n" + "\n\n".join(intermediate)
    )
    return merged


def _s2_abstract(doi: str) -> Optional[str]:
    """Fetch abstract text from S2 Graph API if available."""
    try:
        url = f"{S2_API}{doi}?fields=title,abstract"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        abs_text = resp.json().get("abstract")
        return abs_text
    except Exception as e:
        logger.debug("S2 abstract fetch failed for %s: %s", doi, e)
        return None

# --------------------------- Fallback helpers --------------------------- #
def _arxiv_abstract(arxiv_id: str) -> Optional[str]:
    """Fetch <summary> text from the arXiv Atom feed (id like 2401.06373)."""
    import xml.etree.ElementTree as ET

    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=id:{arxiv_id}&max_results=1"
    )
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        summary_el = root.find("atom:entry/atom:summary", ns)
        if summary_el is not None and summary_el.text:
            # Collapse whitespace
            return re.sub(r"\s+", " ", summary_el.text.strip())
    except Exception as e:
        logger.debug("ArXiv abstract fetch failed for %s: %s", arxiv_id, e)
    return None

# --------------------------- SummariserAgent --------------------------- #

class SummariserAgent:
    """Create/attach summary → persist to DB → return enriched dict."""

    def run(self, papers_in: List[Dict[str, Any]], state: Dict[str, Any]):
        logger.info("SummariserAgent: %d papers to process", len(papers_in))
        outbound: List[Dict[str, Any]] = []
        for paper in papers_in:
            pdf_url = paper.get("pdf_url", "")
            doi = paper.get("doi")
            summary: Optional[str] = None

            # 1️⃣ Try PDF path
            if pdf_url:
                pdf_bytes = _download_pdf(pdf_url)
                if pdf_bytes:
                    text = _extract_text(pdf_bytes)
                    if text:
                        summary = _map_reduce_summary(_chunk_text(text))
                    else:
                        logger.debug("Extraction failed for %s", paper["paper_id"])
            # 2️⃣ Fallback: semantic‑scholar abstract
            if summary is None and doi:
                abs_text = _s2_abstract(doi)
                if abs_text:
                    summary = _openai_summarise(abs_text)
            # 2️⃣ Fallback: arXiv abstract
            if summary is None and paper["paper_id"].startswith("arxiv:"):
                abs_text = _arxiv_abstract(paper["paper_id"].split(":", 1)[1])
                if abs_text:
                    summary = _openai_summarise(abs_text)
            # 3️⃣ Persist if we got something
            if summary:
                paper_with_summary = {**paper, "summary": summary}
                outbound.append(paper_with_summary)
                self._persist_summary(paper["paper_id"], summary)
            else:
                logger.warning("Skip %s – no usable text", paper["paper_id"])
        return outbound, state

    # ------------------------------------------------------------------ #
    def _persist_summary(self, paper_id: str, summary: str):
        with engine.begin() as conn:
            conn.execute(update(papers).where(papers.c.id == paper_id).values(summary=summary))
        logger.debug("Saved summary for %s", paper_id)


# --------------------------- CLI smoke test --------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    test = {
        "paper_id": "arxiv:2401.00001",
        "doi": "10.48550/arXiv.2401.00001",
        "title": "Test Paper",
        "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
    }
    out, _ = SummariserAgent().run([test], {})
    print(textwrap.shorten(str(out), 300))
