import os
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from sources.registry import resolve
from helpers.markdown import write_capture
from errors import classify, IngestError

router = APIRouter(tags=["ingest"])

# Limit concurrent heavy ingests so a batch of links doesn't thrash the CPU
# (Whisper/OCR) and blow past the caller's timeout.
_SEM = threading.Semaphore(int(os.getenv("MAX_CONCURRENT_INGESTS", "2")))


class IngestRequest(BaseModel):
    url: str


@router.post("/ingest")
@router.post("/n8n/ingest")
def ingest(req: IngestRequest):
    """Capture one URL (any supported source) as a raw/ document for the wiki.

    Always returns HTTP 200; failures come back as {success:false, user_message}
    so the Telegram reply can show a friendly message instead of a stack trace.
    """
    try:
        with _SEM:
            source = resolve(req.url)
            cap = source.fetch(req.url)
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
    except Exception as e:
        code, user_message, detail = classify(e)
        return {
            "success": False,
            "error_code": code,
            "user_message": user_message,
            "detail": str(detail)[:500],
        }
