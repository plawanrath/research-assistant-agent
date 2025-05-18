from sqlalchemy import create_engine, Table, Column, Text, MetaData, DateTime, Integer, Float
from datetime import datetime

engine = create_engine("sqlite:///guild.db")
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
meta.create_all(engine)