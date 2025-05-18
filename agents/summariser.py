"""
SummariserAgent – token-aware + robust fallback + future-ideas
-------------------------------------------------------------
* Splits long PDF text with **tiktoken** (≤ 4 000 tokens/chunk) and
  recursively summarises to a 5-line abstract.
* If PDF download/text fails:
    ① fetch abstract from arXiv / Semantic Scholar
    ② **parallel** LLM “web-search” summary from the title
    → use LLM result if available, else abstract.
* Generates 3-5 future-improvement ideas per paper and stores them in
  `future_ideas` table.
* Persists summary into `papers` table.

Env
----
OPENAI_API_KEY
OPENAI_MODEL   (default: gpt-4o-mini)
SEMANTIC_SCHOLAR_API_KEY (optional, higher quota)
"""

from __future__ import annotations
import io, logging, os, re, threading
from typing import List, Dict, Any, Optional

import openai, tiktoken, requests
from PyPDF2 import PdfReader
from sqlalchemy import update, insert

from services.storage import engine, papers, future_ideas  # type: ignore

logger = logging.getLogger(__name__)

# ----------------------- config --------------------------- #
MODEL  = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ENC    = tiktoken.encoding_for_model(MODEL)
TOKENS_PER_CHUNK = 4000
S2_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------------- PDF helpers ----------------------------- #
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

# ---------------- token utils ----------------------------- #
def _split_tokens(text: str, max_tok: int = TOKENS_PER_CHUNK) -> List[str]:
    toks, buf, out = ENC.encode(text), [], []
    for t in toks:
        buf.append(t)
        if len(buf) >= max_tok:
            out.append(ENC.decode(buf)); buf = []
    if buf:
        out.append(ENC.decode(buf))
    return out

# ---------------- LLM wrappers ---------------------------- #
def _llm(prompt: str, temp: float = 0.2, max_out: int = 256) -> str:
    rsp = openai.chat.completions.create(
        model=MODEL,
        temperature=temp,
        messages=[
            {"role": "system", "content": "You summarise academic text concisely."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_out,
    )
    return rsp.choices[0].message.content.strip()

def _recursive_summarise(chunks: List[str]) -> str:
    lvl = 0
    while True:
        if len(chunks) == 1:
            return _llm(chunks[0])
        lvl += 1
        logger.debug(" summarising level %d (%d chunks)", lvl, len(chunks))
        summaries = [_llm(c) for c in chunks]
        merged = "\n\n".join(summaries)
        if len(ENC.encode(merged)) < TOKENS_PER_CHUNK:
            return _llm(merged)
        chunks = _split_tokens(merged)

# -------------- fallback helpers -------------------------- #
def _fetch_abstract(title: str, arxiv_id: str | None) -> Optional[str]:
    # 1) arXiv
    if arxiv_id:
        import xml.etree.ElementTree as ET
        url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        try:
            xml = requests.get(url, timeout=20).text
            root = ET.fromstring(xml)
            summ = root.find('.//{http://www.w3.org/2005/Atom}summary')
            if summ is not None and summ.text:
                return re.sub(r"\s+", " ", summ.text.strip())
        except Exception:
            pass
    # 2) Semantic Scholar by title
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        r = requests.get(
            url,
            params={"query": f'title:"{title}"', "limit": 1, "fields": "abstract"},
            headers={"x-api-key": S2_KEY} if S2_KEY else {},
            timeout=20,
        ).json()
        if r.get("data"):
            return r["data"][0].get("abstract")
    except Exception:
        pass
    return None

def _llm_title_summary(title: str) -> Optional[str]:
    prompt = (
        "You are a research assistant with web access. "
        f"Summarise the scientific paper titled '{title}' in 4 bullet points, "
        "as if you found it online."
    )
    try:
        return _llm(prompt, temp=0.3, max_out=250)
    except Exception as e:
        logger.warning("title-LLM failed: %s", e); return None

# -------------- future-ideas helpers ---------------------- #
def _trim_for_llm(text: str, max_tok: int = TOKENS_PER_CHUNK) -> str:
    toks = ENC.encode(text)
    if len(toks) <= max_tok:
        return text
    # keep head + tail context
    head = toks[: max_tok // 2]
    tail = toks[-max_tok // 2 :]
    return ENC.decode(head) + "\n\n[…trimmed…]\n\n" + ENC.decode(tail)

def _ideas_from_llm(content: str, title: str) -> Optional[str]:
    safe_content = _trim_for_llm(content)
    prompt = (
        f"Paper title: {title}\n\n"
        f"Content / summary (trimmed):\n{safe_content}\n\n"
        "List 3–5 concrete future research directions or improvements."
    )
    try:
        return _llm(prompt, temp=0.4, max_out=300)
    except Exception as e:
        logger.warning("ideas-LLM failed: %s", e)
        return None

def _save_ideas(pid: str, ideas_txt: str):
    with engine.begin() as conn:
        conn.execute(insert(future_ideas).values(paper_id=pid, ideas=ideas_txt))

# --------------------- Agent ------------------------------ #
class SummariserAgent:
    def run(self, papers_in: List[Dict[str, Any]], state: Dict[str, Any]):
        logger.info("SummariserAgent: %d papers", len(papers_in))
        out: List[Dict[str, Any]] = []

        for p in papers_in:
            pid, title = p["paper_id"], p.get("title", "")
            arx_id = pid.split(":", 1)[1] if pid.startswith("arxiv:") else None
            summary: Optional[str] = None
            full_text: Optional[str] = None

            # ---------- 1) try PDF ----------
            if p.get("pdf_url"):
                pdf = _download_pdf(p["pdf_url"])
                if pdf:
                    full_text = _pdf_text(pdf)
                    if full_text:
                        summary = _recursive_summarise(_split_tokens(full_text))

            # ---------- 2) robust fallback ----------
            if summary is None:
                abs_res, llm_res = None, None

                t1 = threading.Thread(target=lambda: globals().update(
                     abs_res=_fetch_abstract(title, arx_id)))
                t2 = threading.Thread(target=lambda: globals().update(
                     llm_res=_llm_title_summary(title)))
                t1.start(); t2.start(); t1.join(); t2.join()

                fallback_txt = llm_res or abs_res
                if fallback_txt:
                    summary = _llm(fallback_txt)
                else:
                    logger.warning("Skip %s – no usable text", pid)
                    continue  # next paper

            # ---------- 3) future ideas ----------
            ideas = _ideas_from_llm(full_text or summary, title)
            if ideas:
                _save_ideas(pid, ideas)

            # ---------- 4) persist summary ----------
            self._save_summary(pid, summary)
            p["summary"] = summary
            out.append(p)

        return out, state

    @staticmethod
    def _save_summary(pid: str, summary: str):
        with engine.begin() as conn:
            conn.execute(update(papers).where(papers.c.id == pid).values(summary=summary))
        logger.debug("Saved summary for %s", pid)


# ------------------ CLI smoke-test ------------------------ #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    demo = {
        "paper_id": "arxiv:2401.00001",
        "doi": "10.48550/arXiv.2401.00001",
        "title": "Example Paper",
        "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
    }
    agent = SummariserAgent()
    res, _ = agent.run([demo], {})
    print(res[0]["summary"][:400])
