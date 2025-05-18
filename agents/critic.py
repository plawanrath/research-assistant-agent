"""
CriticAgent – evaluates each summarised paper on
  • novelty / significance
  • methodological soundness
  • relevance to the topic
and stores (0-10) scores plus a brief critique into SQLite.

Env:
    OPENAI_API_KEY   – required
    OPENAI_MODEL     – default "gpt-4o-mini"
"""

from __future__ import annotations
import logging, os, json
from typing import Any, Dict, List

import openai
from sqlalchemy import update, select
from services.storage import engine, papers  # type: ignore

logger = logging.getLogger(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")
_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are an expert peer reviewer.
Given a 5-line abstract, rate and briefly critique the work on:
1. Novelty / Significance
2. Methodological Soundness
3. Relevance to AI Safety research (0-10 each, integers).

Return STRICT JSON exactly like:
{
  "novelty": 7,
  "methodology": 5,
  "relevance": 8,
  "critique": "one concise paragraph"
}
"""


def _review(summary: str) -> Dict[str, Any] | None:
    """Call OpenAI and parse the strict-JSON response; return None on error."""
    try:
        resp = openai.chat.completions.create(
            model=_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": summary},
            ],
            max_tokens=256,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.warning("Critique failed: %s", e)
        return None


class CriticAgent:
    """LangGraph node – takes list of summarised paper dicts, returns same dicts w/ scores."""

    def __init__(self, min_summary_len: int = 50):
        self._min_len = min_summary_len

    def run(self, papers_in: List[Dict[str, Any]], state: Dict[str, Any]):
        logger.info("CriticAgent: %d papers to critique", len(papers_in))
        outbound: List[Dict[str, Any]] = []
        for p in papers_in:
            summ = p.get("summary", "")
            if len(summ) < self._min_len:
                logger.debug("Skip %s – summary too short", p["paper_id"])
                continue
            review = _review(summ)
            if not review:
                continue

            # Merge results into the paper dict
            p.update(
                score_novelty=str(review["novelty"]),
                score_method=str(review["methodology"]),
                score_relevance=str(review["relevance"]),
                critique=review["critique"],
            )
            outbound.append(p)
            self._persist(p["paper_id"], review)
        return outbound, state

    # -------------------- DB persistence -------------------- #
    @staticmethod
    def _persist(pid: str, r: Dict[str, Any]):
        with engine.begin() as conn:
            conn.execute(
                update(papers)
                .where(papers.c.id == pid)
                .values(
                    score_novelty=r["novelty"],
                    score_method=r["methodology"],
                    score_relevance=r["relevance"],
                    critique=r["critique"],
                )
            )
        logger.debug("Saved critique for %s", pid)


# --------------- CLI smoke-test --------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    # Fetch one paper with a summary from DB and critique it
    with engine.connect() as c:
        row = c.execute(
            select(papers).where(papers.c.summary != "").limit(1)
        ).fetchone()
    if row:
        agent = CriticAgent()
        out, _ = agent.run(
            [
                {
                    "paper_id": row.id,
                    "summary": row.summary,
                }
            ],
            {},
        )
        print(json.dumps(out, indent=2))
    else:
        print("No summarised papers found – run the Summariser first.")
