import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import TEMP_DIR
from helpers.scrapper import fetch_reel
from helpers.transcribe import transcribe_audio
from helpers.frames import extract_keyframes
from helpers.ocr import ocr_images
from helpers.markdown import build_markdown, write_raw_file

router = APIRouter(prefix="/n8n", tags=["n8n"])


class IngestRequest(BaseModel):
    url: str


@router.post("/ingest")
def ingest(req: IngestRequest):
    """Capture one Instagram reel/post as a raw/ source document for the wiki.

    url -> yt-dlp (video/images + metadata)
        -> Whisper transcript (spoken) + RapidOCR on-screen text (visual)
        -> markdown -> <VAULT_RAW_DIR>/<INSTAGRAM_SUBDIR>/<date>-<handle>-<code>.md
    """
    temp_files = []
    try:
        meta = fetch_reel(req.url)
        temp_files = list(meta.get("temp_files") or [])

        # Spoken content (only when there is a video / audio track).
        transcript = {"text": "", "segments": [], "language": None}
        ocr_targets = list(meta.get("image_paths") or [])

        video_path = meta.get("video_path")
        if video_path:
            transcript = transcribe_audio(video_path)
            frames = extract_keyframes(video_path, TEMP_DIR)
            temp_files += frames
            ocr_targets += frames

        # Visual / on-screen text.
        ocr_blocks = ocr_images(ocr_targets) if ocr_targets else []

        content = build_markdown(meta, transcript, ocr_blocks)
        path = write_raw_file(meta, content)

        return {
            "success": True,
            "file": path,
            "shortcode": meta.get("shortcode"),
            "author": meta.get("uploader_handle") or meta.get("uploader"),
            "language": transcript.get("language"),
            "transcript_chars": len(transcript.get("text") or ""),
            "caption_chars": len(meta.get("caption") or ""),
            "ocr_blocks": len(ocr_blocks),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Media (video, images, frames) is only needed during processing.
        for f in temp_files:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
