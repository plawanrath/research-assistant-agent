from sqlalchemy import String, create_engine, Table, Column, Text, MetaData, DateTime, Integer, Float
from datetime import datetime, timezone
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)          # ← ensure dir

DB_PATH = DATA_DIR / "guild.db"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
meta = MetaData()
papers = Table("papers", meta,
    Column("id", Text, primary_key=True),
    Column("title", Text), Column("summary", Text),
    Column("pdf_url", Text),
    Column("embedding", Text),  # JSON list
    Column("score_novelty",  Text),        # store as string to avoid migrations
    Column("score_method",   Text),
    Column("score_relevance",Text),
    Column("critique",       Text),
    Column("created_at", DateTime, default=datetime.utcnow),
)

trends = Table(
    "trends",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trend_label", Text),
    Column("paper_ids", Text),          # JSON list of ids in this cluster
    Column("count", Integer),
    Column("growth", Float),            # % growth week-over-week
    Column("computed_at", DateTime, default=datetime.utcnow),
)
meta.create_all(engine)

plans = Table(
    "plans",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("plan_text", Text),
    Column("created_at", DateTime, default=datetime.utcnow),
)

jobs = Table(
    "jobs", meta,
    Column("id", String, primary_key=True),
    Column("topic", Text),
    Column("days", Integer),
    Column("max_results", Integer),
    Column("status", String),          # queued | running | done | failed
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("error", Text),
)

logs = Table(
    "logs", meta,
    Column("job_id", String),
    Column("ts", DateTime),
    Column("msg", Text),
)

results = Table(
    "results", meta,
    Column("job_id", String, primary_key=True),
    Column("reading_plan", Text),
    Column("trends_json", Text),
    Column("papers_json", Text),
)

meta.create_all(engine)

# helper for tasks
def append_log(job_id: str, msg: str):
    from sqlalchemy import insert
    with engine.begin() as conn:
        conn.execute(insert(logs).values(job_id=job_id, ts=datetime.now(timezone.utc), msg=msg))