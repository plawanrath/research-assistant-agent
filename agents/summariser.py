"""
SummariserAgent – token-aware version
------------------------------------
* Splits text by **tiktoken** tokens (≤4 000 each).
* Recursively summarises chunks with OpenAI → final 5-line abstract.
* Falls back to Semantic Scholar or arXiv abstracts when no PDF text.
* Persists summary into `papers` table.

Env
----
OPENAI_API_KEY   – required
OPENAI_MODEL     – default: gpt-4o-mini
"""

from __future__ import annotations
import io, logging, os, re, json, requests
from typing import List, Dict, Any, Optional

import openai, tiktoken
from PyPDF2 import PdfReader
from sqlalchemy import update
from services.storage import engine, papers  # type: ignore

logger = logging.getLogger(__name__)

# -------- config -------- #
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ENC   = tiktoken.encoding_for_model(MODEL)
TOKENS_PER_CHUNK = 4000          # 4k in, 256 out
S2_API = "https://api.semanticscholar.org/graph/v1/paper/"
openai.api_key = os.getenv("OPENAI_API_KEY")

# -------- helpers -------- #
def _download_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
        r.raise_for_status()
        return r.content if r.content.startswith(b"%PDF") else None
    except Exception as e:
        logger.warning("PDF download failed %s: %s", url, e)
        return None

def _pdf_text(data: bytes) -> Optional[str]:
    try:
        pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]
        return "\n".join(pages)
    except Exception as e:
        logger.debug("PDF parse error: %s", e)
        return None

def _split_tokens(text: str, max_tok: int = TOKENS_PER_CHUNK) -> List[str]:
    toks = ENC.encode(text)
    chunks, buf = [], []
    for tok in toks:
        buf.append(tok)
        if len(buf) >= max_tok:
            chunks.append(ENC.decode(buf)); buf = []
    if buf:
        chunks.append(ENC.decode(buf))
    return chunks

def _llm(text: str) -> str:
    resp = openai.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You summarise academic text concisely."},
            {"role": "user", "content": text},
        ],
        max_tokens=256,
    )
    return resp.choices[0].message.content.strip()

def _recursive_summarise(chunks: List[str]) -> str:
    level = 0
    while True:
        if len(chunks) == 1:
            return _llm(chunks[0])
        level += 1
        logger.debug("  summarising level %d (%d chunks)", level, len(chunks))
        summaries = [_llm(c) for c in chunks]
        merged = "\n\n".join(summaries)
        if len(ENC.encode(merged)) < TOKENS_PER_CHUNK:
            return _llm(merged)
        chunks = _split_tokens(merged)

# --- fallback abstracts --- #
def _s2_abstract(doi: str) -> Optional[str]:
    try:
        url = f"{S2_API}{doi}?fields=abstract"
        r = requests.get(url, timeout=20); r.raise_for_status()
        return r.json().get("abstract")
    except Exception as e:
        logger.debug("S2 abstract fail %s: %s", doi, e); return None

def _arxiv_abstract(arxiv_id: str) -> Optional[str]:
    import xml.etree.ElementTree as ET
    url = f"http://export.arxiv.org/api/query?search_query=id:{arxiv_id}&max_results=1"
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=20); r.raise_for_status()
        root = ET.fromstring(r.text)
        ns={"a":"http://www.w3.org/2005/Atom"}
        el = root.find("a:entry/a:summary", ns)
        if el is not None and el.text:
            return re.sub(r"\s+", " ", el.text.strip())
    except Exception as e:
        logger.debug("arXiv abstract fail %s: %s", arxiv_id, e)
    return None

# --------- agent --------- #
class SummariserAgent:
    def run(self, papers_in: List[Dict[str, Any]], state: Dict[str, Any]):
        logger.info("SummariserAgent: %d papers", len(papers_in))
        out = []
        for p in papers_in:
            summary: Optional[str] = None

            # 1. PDF path
            if p.get("pdf_url"):
                pdf = _download_pdf(p["pdf_url"])
                if pdf:
                    text = _pdf_text(pdf)
                    if text:
                        chunks = _split_tokens(text)
                        summary = _recursive_summarise(chunks)

            # 2. Semantic-Scholar abstract
            if summary is None and p.get("doi"):
                abs_text = _s2_abstract(p["doi"])
                if abs_text:
                    summary = _llm(abs_text)

            # 3. arXiv abstract
            if summary is None and p["paper_id"].startswith("arxiv:"):
                aid = p["paper_id"].split(":",1)[1]
                abs_text = _arxiv_abstract(aid)
                if abs_text:
                    summary = _llm(abs_text)

            if summary:
                p["summary"] = summary
                out.append(p)
                self._save(p["paper_id"], summary)
            else:
                logger.warning("Skip %s – no usable text", p["paper_id"])
        return out, state

    @staticmethod
    def _save(pid: str, summary: str):
        with engine.begin() as conn:
            conn.execute(update(papers).where(papers.c.id == pid).values(summary=summary))
        logger.debug("Saved summary for %s", pid)

# CLI smoke-test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    demo = {"paper_id":"arxiv:2401.00001","doi":"10.48550/arXiv.2401.00001",
            "pdf_url":"https://arxiv.org/pdf/2401.00001.pdf"}
    print(SummariserAgent().run([demo], {})[0][0]["summary"][:300])
