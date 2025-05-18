# api.py  – FastAPI server
import os
import uuid, datetime as dt, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text, desc
from services.storage import engine, jobs, logs, results
from tasks import pipeline_task

app = FastAPI(title="Research Assistant")

_ALLOWED = os.getenv("CORS_ORIGINS", "").split(",") or ["*"]   # * = wide-open

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED,           # e.g. ["https://app.your-domain.com"]
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

def _row_to_dict(row):
    return dict(row._mapping)

class JobRequest(BaseModel):
    topic: str
    days: int  = 2
    max_results: int = 25

@app.post("/jobs", status_code=202)
def start_job(req: JobRequest):
    job_id = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(jobs.insert().values(
            id=job_id, topic=req.topic, days=req.days, max_results=req.max_results,
            status="queued", started_at=dt.datetime.utcnow()))
    pipeline_task.delay(job_id, req.topic, req.days, req.max_results)
    return {"job_id": job_id, "status": "queued"}

@app.get("/jobs")                                 # e.g.  GET /jobs?status=done
def list_jobs(status: str | None = None):
    with engine.connect() as c:
        q = select(
                jobs.c.id,
                jobs.c.topic,
                jobs.c.status,
                jobs.c.started_at,
                jobs.c.finished_at,
            ).order_by(desc(jobs.c.started_at))
        if status:
            q = q.where(jobs.c.status == status)
        rows = c.execute(q).mappings().all()
    return rows        # FastAPI auto-serialises list[dict]

@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    with engine.connect() as c:
        row = c.execute(select(jobs).where(jobs.c.id == job_id)).fetchone()
        if not row:
            raise HTTPException(404, "job not found")
        log_txt = "\n".join(
            r.msg for r in c.execute(select(logs.c.msg)
                                     .where(logs.c.job_id == job_id)
                                     .order_by(logs.c.ts))
        )
    return _row_to_dict(row) | {"logs": log_txt}

@app.get("/jobs/{job_id}/result")
def job_result(job_id: str):
    with engine.connect() as c:
        row = c.execute(select(results).where(results.c.job_id==job_id)).fetchone()
        if not row: raise HTTPException(404, "results not ready")
    return _row_to_dict(row)

@app.post("/admin/clear", status_code=204)
def clear_everything():
    """Dangerous: wipe papers, trends, plans, jobs, logs, results."""
    tables = ["papers", "trends", "plans", "jobs", "logs", "results"]
    with engine.begin() as conn:
        for tbl in tables:
            conn.execute(text(f"DELETE FROM {tbl}"))
    return  # 204 No Content