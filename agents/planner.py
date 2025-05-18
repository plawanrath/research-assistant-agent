"""
PlannerAgent
============
Takes scored & critiqued papers, builds a 5-item reading queue,
and stores it in the `plans` table.

Logic
------
* Score = 0.6 · relevance  + 0.4 · novelty   (out of 10)
* Choose top 5 papers from the last 14 days
* Ask GPT-4o-mini to write a friendly reading plan

Env
----
OPENAI_API_KEY   – required
OPENAI_MODEL     – default gpt-4o-mini
"""

from __future__ import annotations
import logging, os, json
from datetime import datetime, timedelta
from typing import Any, Dict, List

import openai
from sqlalchemy import select, insert, delete

from services.storage import engine, papers, plans  # type: ignore

logger = logging.getLogger(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class PlannerAgent:
    def __init__(self, days_back: int = 14, top_n: int = 5):
        self.days_back = days_back
        self.top_n = top_n

    # ------------------------------------------------------------------ #
    def run(self, _msg: Any, state: Dict[str, Any]):
        logger.info("PlannerAgent: Creating a plan …")
        cutoff = datetime.utcnow() - timedelta(days=self.days_back)

        # 1️⃣  pull candidate papers
        with engine.connect() as conn:
            rows = conn.execute(
                select(
                    papers.c.id,
                    papers.c.title,
                    papers.c.pdf_url,
                    papers.c.summary,
                    papers.c.score_novelty,
                    papers.c.score_relevance,
                    papers.c.created_at,
                ).where(
                    (papers.c.summary != "") & (papers.c.created_at >= cutoff)
                )
            ).fetchall()

        if not rows:
            logger.info("PlannerAgent: nothing to plan yet")
            return state, {}

        # 2️⃣  rank
        scored = []
        for r in rows:
            try:
                novelty   = float(r.score_novelty or 0)
                relevance = float(r.score_relevance or 0)
            except ValueError:
                continue
            score = 0.4 * novelty + 0.6 * relevance
            scored.append((score, r))

        scored.sort(reverse=True)
        chosen = scored[: self.top_n]

        # 3️⃣  ask GPT to draft the plan
        bullets = []
        for rank, (_, r) in enumerate(chosen, start=1):
            bullets.append(f"{rank}. **{r.title}** ([PDF]({r.pdf_url}))")

        user_prompt = (
            "Create a friendly 1-paragraph intro followed by this numbered list "
            "as my reading queue.  Keep it motivating and concise.\n\n"
            + "\n".join(bullets)
        )

        resp = openai.chat.completions.create(
            model=MODEL,
            temperature=0.7,
            messages=[
                {"role": "system", "content": "You are my reading-plan assistant."},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
        )
        plan_text = resp.choices[0].message.content.strip()

        # 4️⃣  persist (one snapshot only)
        with engine.begin() as conn:
            conn.execute(delete(plans))  # keep latest plan only
            conn.execute(
                insert(plans).values(plan_text=plan_text, created_at=datetime.utcnow())
            )
        logger.info("PlannerAgent: saved new plan")
        return state, {}