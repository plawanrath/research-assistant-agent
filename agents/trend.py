"""
TrendAnalyzerAgent
------------------
* Builds / refreshes embeddings for every summarised paper
  (OpenAI text-embedding-3-small).
* Clusters embeddings with MiniBatchKMeans.
* Labels each cluster via top TF-IDF terms from summaries.
* Compares paper-counts   → last 7 days vs previous 7 days.
* Persists the 5 fastest-growing clusters to `trends` table.
"""
# agents/trend.py  (updated)
from __future__ import annotations
import json, logging, math, os
from datetime import datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import openai
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select, update, insert, delete
from services.storage import engine, papers, trends  # type: ignore

openai.api_key = os.getenv("OPENAI_API_KEY")
EMBED_MODEL   = "text-embedding-3-small"
logger        = logging.getLogger(__name__)

# ---------------- helpers ---------------- #
def _embedding(text: str) -> List[float]:
    emb = openai.embeddings.create(model=EMBED_MODEL, input=text).data[0].embedding
    return emb

def _ensure_embeddings() -> List[Dict[str, Any]]:
    """Return rows with id, summary, embedding, created_at (ensure embedding exists)."""
    out = []
    with engine.begin() as conn:
        rows = conn.execute(
            select(
                papers.c.id,
                papers.c.summary,
                papers.c.embedding,
                papers.c.created_at,
            ).where(papers.c.summary != "")
        ).fetchall()

        for rid, summ, emb_json, created in rows:
            emb = json.loads(emb_json) if emb_json and emb_json != "[]" else None
            if emb is None:
                emb = _embedding(summ)
                conn.execute(
                    update(papers)
                    .where(papers.c.id == rid)
                    .values(embedding=json.dumps(emb))
                )
            out.append(
                {
                    "id": rid,
                    "summary": summ,
                    "embedding": emb,
                    "created": created or datetime(1970, 1, 1),
                }
            )
    return out

# ------------- TrendAnalyzerAgent -------- #
class TrendAnalyzerAgent:
    def __init__(self, lookback_days: int = 30, top_k: int = 5):
        self.lookback = lookback_days
        self.top_k    = top_k

    def run(self, _msg: Any, state: Dict[str, Any]):
        logger.info("TrendAnalyzerAgent: computing trends …")
        rows = _ensure_embeddings()
        if len(rows) < 8:
            logger.info("Not enough data yet (%d papers)", len(rows))
            return [], state

        X = np.array([r["embedding"] for r in rows])
        k = min(8, int(math.sqrt(len(rows)))) or 2
        labels = MiniBatchKMeans(n_clusters=k, random_state=42).fit_predict(X)

        # TF-IDF labels
        tfidf = TfidfVectorizer(stop_words="english", max_features=3000)
        tfidf.fit([r["summary"] for r in rows])
        vocab   = {i: w for w, i in tfidf.vocabulary_.items()}
        clusters = {i: [] for i in range(k)}
        for r, lab in zip(rows, labels):
            clusters[lab].append(r["summary"])

        lab_names = {}
        for lab, texts in clusters.items():
            vec = tfidf.transform(texts).mean(axis=0)
            top = np.asarray(vec.A).ravel().argsort()[-3:][::-1]
            lab_names[lab] = " / ".join(vocab.get(i, "") for i in top)

        now        = datetime.utcnow()
        last_week  = now - timedelta(days=7)
        prev_week  = last_week - timedelta(days=7)
        counts, counts_prev = {i:0 for i in range(k)}, {i:0 for i in range(k)}

        for r, lab in zip(rows, labels):
            created = r["created"]
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            if created >= last_week:
                counts[lab] += 1
            elif created >= prev_week:
                counts_prev[lab] += 1

        with engine.begin() as conn:
            conn.execute(delete(trends))      # keep only latest snapshot
            scored = []
            for lab in range(k):
                prev = counts_prev[lab] or 1
                growth = (counts[lab] - counts_prev[lab]) / prev
                scored.append((growth, lab, counts[lab], lab_names[lab]))
            scored.sort(reverse=True)

            for g, lab, cnt, label in scored[: self.top_k]:
                sorted_ids = [
                    r["id"]
                    for r, l in sorted(
                        zip(rows, labels),
                        key=lambda p: p[0]["created"],   # sort by created datetime
                        reverse=True,
                    )
                    if l == lab
                ]
                conn.execute(
                    insert(trends).values(
                        trend_label = label,
                        paper_ids   = json.dumps(sorted_ids),
                        count       = cnt,
                        growth      = round(g, 2),
                        computed_at = now,
                    )
                )
        logger.info("TrendAnalyzerAgent: saved trends snapshot")
        return [], state

# ---------------- CLI test ---------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    TrendAnalyzerAgent().run(None, {})
