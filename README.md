Research Assistant Agent

```
                ┌───────────────┐
   text_input → │  Streamlit UI │─┐
                └───────────────┘ │  starts worker-thread
                                   ▼
                           ┌────────────────┐
                           │ run_pipeline() │──> LangGraph (all agents)
                           └────────────────┘
                                     │ puts log lines
                                     ▼
                          ┌───────────────────┐
                          │   log_queue       │
                          └───────────────────┘
                                     │
                    UI polls ⇒   live INFO log stream
```


```
research-guild/
├ agents/                single-task LLM agents (fetcher, summariser…)
├ services/
│   ├ storage.py         DB connection + table definitions
│   └ vector.py          (placeholder for embeddings)
├ ui/
│   └ app.py             Streamlit frontend (pure HTTP)
├ guild_graph.py         LangGraph orchestrator reused by the worker
├ api.py                 REST API  (jobs, logs, results, admin/clear)
├ tasks.py               Celery task wrapper  ➜ calls guild_graph
├ Dockerfile             builds one image for api + worker + streamlit
├ docker-compose.yml     spins up: redis · api · worker · streamlit
├ requirements.txt       pip dependencies
└ README.md              (this file)
```


## How to Run

```
git clone https://github.com/plawanrath/research-assistant-agent.git
cd research-assistant-agent

# 1. secrets
touch .env           # add your OPENAI_API_KEY, optional REDIS_URL

# 2. make data dir (git-ignored)
mkdir -p data

# 3. build + run everything
docker compose up --build
```

- UI: http://localhost:8501
- API: API: http://localhost:8000 

## Creating User

```
python - <<'PY'                             
import bcrypt, sqlalchemy as sa, services.storage as s
pwd = bcrypt.hashpw(b"<password>", bcrypt.gensalt()).decode()
with s.engine.begin() as conn:
    conn.execute(sa.insert(s.users).values(username="<username>", pwd_hash=pwd))
PY
```