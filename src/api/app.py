"""FastAPI application entrypoint.

Run it (from the repo root) with:

    uvicorn api.app:app --app-dir src --reload --port 8000

It reuses the existing CLI modules (sync_tracker, prune_deleted, sync_env_tags,
export, dify_api, confluence, slack_notify) as the business layer. All Dify /
Confluence / Slack operations run as the service account configured in `.env`;
the per-user login only authenticates access to this app and resolves roles.
"""

import os
import sys
from pathlib import Path

# Make the sibling CLI modules (dify_api, confluence, ...) importable as
# top-level modules whether we are launched via uvicorn --app-dir src or python.
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

load_dotenv(SRC_DIR.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from api import auth, jobs, workflows

app = FastAPI(title="Dify Workflow Console", version="0.1.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-insecure-secret-change-me"),
    same_site="lax",
    https_only=False,
)

# The Next.js dev server proxies /api to this backend, but allow direct
# cross-origin calls from the dev frontend too (with credentials).
_origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(workflows.router)
app.include_router(jobs.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
