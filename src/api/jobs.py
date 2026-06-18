"""Background job runner for the action buttons (sync / tags / export / prune).

Jobs run one-at-a-time on a single worker thread. This is intentional: several
of these operations write the same Confluence page, so they must not overlap
(mirrors the GitHub Actions `concurrency` group). Each job captures stdout and
log output so the UI can tail it live over SSE.

State is in-memory only; it is lost on restart. Persistent history is a planned
later phase.
"""

import asyncio
import contextlib
import io
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

import export
import prune_deleted
import sync_env_tags
import sync_tracker
from api.auth import require_admin, require_auth

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# job_id -> job dict. Ordered by insertion (Python dicts preserve order).
_JOBS: "dict[str, dict]" = {}
_QUEUE: "queue.Queue[str]" = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False
_MAX_JOBS = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _LogWriter(io.TextIOBase):
    """File-like object that appends complete lines to a job's log list."""

    def __init__(self, job: dict):
        self._job = job
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._job["log"].append(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._job["log"].append(self._buf)
            self._buf = ""


def _run_one(job: dict) -> None:
    job["status"] = "running"
    job["started_at"] = _now()
    writer = _LogWriter(job)
    handler = logging.StreamHandler(writer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            result = job["fn"]()
        job["result"] = result if isinstance(result, (dict, list)) else {"value": str(result)}
        job["status"] = "success"
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        job["log"].append(f"ERROR: {exc}")
        job["error"] = str(exc)
        job["status"] = "error"
    finally:
        writer.flush()
        root.removeHandler(handler)
        job["finished_at"] = _now()


def _worker() -> None:
    while True:
        job_id = _QUEUE.get()
        job = _JOBS.get(job_id)
        if job is not None:
            _run_one(job)
        _QUEUE.task_done()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True, name="job-worker").start()
            _worker_started = True


def _enqueue(job_type: str, fn, meta: dict | None = None) -> dict:
    _ensure_worker()
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "log": [],
        "result": None,
        "error": None,
        "meta": meta or {},
        "fn": fn,
    }
    _JOBS[job_id] = job
    # Trim old jobs to bound memory.
    while len(_JOBS) > _MAX_JOBS:
        oldest = next(iter(_JOBS))
        if _JOBS[oldest]["status"] in ("queued", "running"):
            break
        _JOBS.pop(oldest, None)
    _QUEUE.put(job_id)
    return _public(job)


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "fn"}


class PruneBody(BaseModel):
    confirm: bool = False


@router.post("/sync")
def start_sync(user: dict = Depends(require_auth)) -> dict:
    return _enqueue("sync", lambda: sync_tracker.run(dry_run=False, notify=True), {"by": user["email"]})


@router.post("/tags")
def start_tags(user: dict = Depends(require_auth)) -> dict:
    return _enqueue("tags", lambda: sync_env_tags.run(dry_run=False), {"by": user["email"]})


@router.post("/export")
def start_export(user: dict = Depends(require_auth)) -> dict:
    return _enqueue("export", lambda: asyncio.run(export.main()) or {"ok": True}, {"by": user["email"]})


@router.post("/prune")
def start_prune(body: PruneBody, user: dict = Depends(require_admin)) -> dict:
    mode = "prune (delete)" if body.confirm else "prune (dry-run)"
    return _enqueue(
        "prune" if body.confirm else "prune-preview",
        lambda: prune_deleted.run(confirm=body.confirm, notify=True),
        {"by": user["email"], "mode": mode},
    )


@router.get("")
def list_jobs(user: dict = Depends(require_auth)) -> dict:
    jobs = [_public(j) for j in _JOBS.values()]
    # Most recent first, and don't ship full logs in the list view.
    for j in jobs:
        j["log_lines"] = len(j["log"])
        j.pop("log", None)
    return {"jobs": list(reversed(jobs))}


@router.get("/{job_id}")
def get_job(job_id: str, user: dict = Depends(require_auth)) -> dict:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, user: dict = Depends(require_auth)) -> StreamingResponse:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_gen():
        sent = 0
        while True:
            log = job["log"]
            while sent < len(log):
                line = log[sent]
                sent += 1
                yield f"data: {line}\n\n"
            if job["status"] in ("success", "error") and sent >= len(job["log"]):
                yield f"event: end\ndata: {job['status']}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
