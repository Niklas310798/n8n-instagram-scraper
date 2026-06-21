"""Fetch a single Instagram reel / post with yt-dlp.

Downloads the actual media (video and/or carousel images) so we can both
transcribe speech and OCR on-screen text. The video file itself is not kept
beyond processing (the route cleans up temp files).
"""
import glob
import os
from typing import Dict
import yt_dlp
from config import TEMP_DIR

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _shortcode(url: str) -> str:
    """Extract the Instagram shortcode from a reel/post URL."""
    parts = [p for p in url.split("?")[0].split("/") if p]
    for i, p in enumerate(parts):
        if p in ("reel", "reels", "p", "tv") and i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else "reel"


def fetch_reel(url: str, output_dir: str = TEMP_DIR) -> Dict:
    """Download media + extract metadata for a single Instagram URL.

    Returns metadata plus:
      - video_path:  path to a downloaded video, or None
      - image_paths: list of downloaded image files (carousels / image posts)
      - temp_files:  every file we created, for cleanup
    """
    os.makedirs(output_dir, exist_ok=True)
    shortcode = _shortcode(url)
    outtmpl = os.path.join(output_dir, f"{shortcode}.%(autonumber)03d.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,  # allow carousels (multiple images/videos)
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Carousels come back as a playlist; post-level metadata sits on `info`.
    files = sorted(glob.glob(os.path.join(output_dir, f"{shortcode}.*")))
    video_path = next((f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS), None)
    image_paths = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]

    if not video_path and not image_paths:
        raise FileNotFoundError(f"yt-dlp produced no media for {url}")

    return {
        "url": info.get("webpage_url") or url,
        "shortcode": shortcode,
        "uploader": info.get("uploader") or info.get("channel"),
        # `channel` holds the @handle (e.g. "callumcarver"); uploader_id is numeric
        "uploader_handle": info.get("channel") or info.get("uploader_id") or info.get("uploader"),
        "title": info.get("title"),
        "caption": info.get("description") or "",
        "timestamp": info.get("timestamp"),
        "upload_date": info.get("upload_date"),  # YYYYMMDD
        "duration": info.get("duration"),
        "like_count": info.get("like_count"),
        "view_count": info.get("view_count"),
        "comment_count": info.get("comment_count"),
        "thumbnail": info.get("thumbnail"),
        "video_path": video_path,
        "image_paths": image_paths,
        "temp_files": list(files),
    }
