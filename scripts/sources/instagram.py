"""Instagram source adapter.

Downloads a reel/post with yt-dlp (video or carousel images), transcribes the
audio, OCRs on-screen text from scene-change keyframes + images, and returns a
normalized Capture. Behaviour is identical to the original single-purpose
pipeline — just wrapped behind the Source interface.
"""
import glob
import os
import yt_dlp

from config import TEMP_DIR
from sources.base import Capture, Source, first_nonempty_line, published_from_ytdlp
from helpers.transcribe import transcribe_audio
from helpers.frames import extract_keyframes
from helpers.ocr import ocr_images

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _shortcode(url: str) -> str:
    parts = [p for p in url.split("?")[0].split("/") if p]
    for i, p in enumerate(parts):
        if p in ("reel", "reels", "p", "tv") and i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else "reel"


class InstagramSource(Source):
    name = "instagram"

    @staticmethod
    def matches(url: str) -> bool:
        return "instagram.com" in url.lower()

    def fetch(self, url: str) -> Capture:
        os.makedirs(TEMP_DIR, exist_ok=True)
        shortcode = _shortcode(url)
        outtmpl = os.path.join(TEMP_DIR, f"{shortcode}.%(autonumber)03d.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": "best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,  # allow carousels
        }

        temp_files = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            files = sorted(glob.glob(os.path.join(TEMP_DIR, f"{shortcode}.*")))
            temp_files = list(files)
            video_path = next((f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS), None)
            image_paths = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
            if not video_path and not image_paths:
                raise FileNotFoundError(f"yt-dlp produced no media for {url}")

            # Spoken content (only when there is a video / audio track).
            transcript = {"text": "", "segments": [], "language": None}
            ocr_targets = list(image_paths)
            if video_path:
                transcript = transcribe_audio(video_path)
                frames = extract_keyframes(video_path, TEMP_DIR)
                temp_files += frames
                ocr_targets += frames

            ocr_blocks = ocr_images(ocr_targets) if ocr_targets else []

            caption = (info.get("description") or "").strip()
            # `channel` holds the @handle (e.g. "callumcarver"); uploader_id is numeric
            handle = info.get("channel") or info.get("uploader_id") or info.get("uploader") or "unknown"
            author = info.get("uploader") or handle
            title = first_nonempty_line(caption) or info.get("title") or f"Instagram Reel {shortcode}"

            metrics = {}
            if info.get("view_count") is not None:
                metrics["views"] = info["view_count"]
            if info.get("like_count") is not None:
                metrics["likes"] = info["like_count"]

            return Capture(
                source="instagram",
                url=info.get("webpage_url") or url,
                source_id=shortcode,
                author=author,
                handle=handle,
                title=title,
                published=published_from_ytdlp(info),
                caption=caption,
                caption_heading="Caption",
                transcript_text=(transcript.get("text") or "").strip(),
                transcript_language=transcript.get("language"),
                ocr_blocks=ocr_blocks,
                metrics=metrics,
                tags=["instagram", "reel", "inbox"],
            )
        finally:
            for f in temp_files:
                try:
                    if f and os.path.exists(f):
                        os.remove(f)
                except OSError:
                    pass
