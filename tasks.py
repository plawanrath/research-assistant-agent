# tasks.py
import os, json, datetime as dt, traceback
from celery import Celery
from sqlalchemy import text
from services.storage import engine, jobs, results, append_log
from guild_graph import ResearchGuildGraph

# Celery app (Redis broker)
celery_app = Celery(
    "guild",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
)


@celery_app.task(bind=True)
def pipeline_task(self, job_id: str, topic: str, days: int, max_results: int):
    """
    Run Fetcher → Summariser → Critic → Trend → Planner and
    snapshot results into the `results` table.
    """

    def log(msg: str):
        append_log(job_id, msg)

    try:
        # mark job running
        with engine.begin() as conn:
            conn.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(status="running", started_at=dt.datetime.utcnow())
            )

        # run full pipeline
        log("Fetcher → Planner pipeline starting")
        rg = ResearchGuildGraph(topic, since_days=days, max_results=max_results)
        rg.run()
        log("Pipeline finished, saving result snapshot")

        # ------------------------------------------------------------------
        # pull key artefacts from DB
        # ------------------------------------------------------------------
        with engine.connect() as conn:
            plan = conn.execute(
                text("SELECT plan_text FROM plans ORDER BY id DESC LIMIT 1")
            ).scalar_one_or_none()

            trends = conn.execute(
                text(
                    "SELECT trend_label, count, growth, paper_ids "
                    "FROM trends ORDER BY id"
                )
            ).mappings().all()
            papers = conn.execute(
                text(
                    "SELECT id, title, pdf_url, summary, "
                    "score_novelty, score_method, score_relevance, COALESCE(created_at, datetime('now')) AS created_at "
                    "FROM papers ORDER BY created_at"
                )
            ).mappings().all()

        # serialise to JSON
        trends_json = json.dumps([dict(r) for r in trends])
        papers_json = json.dumps([dict(r) for r in papers])

        # ------------------------------------------------------------------
        # store snapshot + mark job done
        # ------------------------------------------------------------------
        with engine.begin() as conn:
            conn.execute(
                results.insert().values(
                    job_id=job_id,
                    reading_plan=plan or "",
                    trends_json=trends_json,
                    papers_json=papers_json,
                )
            )
            conn.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(status="done", finished_at=dt.datetime.utcnow())
            )
        log("Snapshot saved – pipeline DONE")

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        with engine.begin() as conn:
            conn.execute(
                jobs.update()
                .where(jobs.c.id == job_id)
                .values(status="failed", error=str(exc), finished_at=dt.datetime.utcnow())
            )
        log(f"ERROR: {exc}")
        raise