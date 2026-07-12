import json
import os
import threading
import time
import urllib.request
import uuid
from queue import Queue
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sources.registry import resolve
from helpers.markdown import write_capture
from errors import classify, IngestError

router = APIRouter(tags=["ingest"])

# Sync requests are still concurrency-limited (protects CPU on small hosts).
_SEM = threading.Semaphore(int(os.getenv("MAX_CONCURRENT_INGESTS", "2")))

# --- async job queue -------------------------------------------------------
# With a callback_url the request returns immediately and a worker processes
# jobs one by one — a batch of 20 links no longer times out the caller.
_JOBS: Dict[str, Dict[str, Any]] = {}
_QUEUE: Queue = Queue()
_WORKERS_LOCK = threading.Lock()
_workers_started = False


class IngestRequest(BaseModel):
    url: str
    callback_url: Optional[str] = None   # POSTed the result JSON when done
    meta: Optional[Dict[str, Any]] = None  # passed through to the callback


def _process(url: str) -> Dict[str, Any]:
    source = resolve(url)
    cap = source.fetch(url)
    # Don't write hollow captures (nothing actually extracted).
    if not (cap.caption.strip() or cap.transcript_text.strip() or cap.ocr_blocks):
        raise IngestError(
            "not_found",
            "🚫 Für diesen Link konnten keine Inhalte extrahiert werden (privat, gelöscht oder Login nötig).")
    path = write_capture(cap)
    kind = next((t for t in cap.tags if t in ("reel", "post", "video")), None)
    return {
        "success": True,
        "file": path,
        "source": cap.source,
        "kind": kind,
        "shortcode": cap.source_id,
        "author": cap.handle,
        "language": cap.transcript_language,
        "transcript_chars": len(cap.transcript_text or ""),
        "caption_chars": len(cap.caption or ""),
        "ocr_blocks": len(cap.ocr_blocks),
    }


def _run_job(job: Dict[str, Any]) -> None:
    job["status"] = "running"
    try:
        result = _process(job["url"])
    except Exception as e:
        code, user_message, detail = classify(e)
        result = {"success": False, "error_code": code,
                  "user_message": user_message, "detail": str(detail)[:500]}
    result["url"] = job["url"]
    result["job_id"] = job["id"]
    result["meta"] = job.get("meta") or {}
    job["result"] = result
    job["status"] = "done"

    cb = job.get("callback_url")
    if cb:
        for _attempt in range(3):
            try:
                req = urllib.request.Request(
                    cb, data=json.dumps(result).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=30)
                break
            except Exception:
                time.sleep(5)


def _worker() -> None:
    while True:
        job_id = _QUEUE.get()
        try:
            _run_job(_JOBS[job_id])
        finally:
            _QUEUE.task_done()


def _ensure_workers() -> None:
    global _workers_started
    with _WORKERS_LOCK:
        if not _workers_started:
            for _ in range(int(os.getenv("INGEST_WORKERS", "1"))):
                threading.Thread(target=_worker, daemon=True).start()
            _workers_started = True


# --- endpoints --------------------------------------------------------------

@router.post("/ingest")
@router.post("/n8n/ingest")
def ingest(req: IngestRequest):
    """Capture one URL as a raw/ document for the wiki.

    Without callback_url: synchronous (result in the response, as before).
    With callback_url: returns immediately; the result JSON (incl. `meta`
    passthrough) is POSTed to callback_url when the job finishes.
    """
    if req.callback_url:
        _ensure_workers()
        job = {"id": uuid.uuid4().hex[:12], "url": req.url, "status": "queued",
               "callback_url": req.callback_url, "meta": req.meta, "result": None}
        _JOBS[job["id"]] = job
        _QUEUE.put(job["id"])
        return {"accepted": True, "job_id": job["id"], "queued": _QUEUE.qsize()}

    try:
        with _SEM:
            return _process(req.url)
    except Exception as e:
        code, user_message, detail = classify(e)
        return {"success": False, "error_code": code,
                "user_message": user_message, "detail": str(detail)[:500]}


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job id")
    return {"job_id": job_id, "status": job["status"], "url": job["url"],
            "result": job["result"]}
