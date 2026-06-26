from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sources.registry import resolve
from helpers.markdown import write_capture

router = APIRouter(tags=["ingest"])


class IngestRequest(BaseModel):
    url: str


# Two paths: /ingest (new, source-agnostic) and /n8n/ingest (kept for the
# existing n8n workflow). Both run the same dispatch.
@router.post("/ingest")
@router.post("/n8n/ingest")
def ingest(req: IngestRequest):
    """Capture one URL (any supported source) as a raw/ document for the wiki."""
    try:
        source = resolve(req.url)
        cap = source.fetch(req.url)
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
        raise HTTPException(status_code=500, detail=str(e))
