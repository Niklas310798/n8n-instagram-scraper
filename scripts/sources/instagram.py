"""Instagram source adapter.

Reels/videos go through yt-dlp (download media, transcribe, OCR keyframes).
Image posts / carousels are not served by yt-dlp (it returns no media), so we
fall back to Apify's Instagram scraper to fetch the carousel images and OCR the
text on them.
"""
import glob
import os
import urllib.request
from datetime import datetime

import yt_dlp

from config import TEMP_DIR, APIFY_API_TOKEN
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
        cap = self._fetch_ytdlp(url)
        if cap is not None:
            return cap
        # yt-dlp found no media -> image post / carousel -> Apify
        return self._fetch_apify(url)

    # --- yt-dlp (reels / videos) ----------------------------------------

    def _fetch_ytdlp(self, url: str):
        os.makedirs(TEMP_DIR, exist_ok=True)
        shortcode = _shortcode(url)
        outtmpl = os.path.join(TEMP_DIR, f"{shortcode}.%(autonumber)03d.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": "best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
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
                return None  # image post -> caller falls back to Apify

            transcript = {"text": "", "segments": [], "language": None}
            ocr_targets = list(image_paths)
            if video_path:
                transcript = transcribe_audio(video_path)
                frames = extract_keyframes(video_path, TEMP_DIR)
                temp_files += frames
                ocr_targets += frames

            ocr_blocks = ocr_images(ocr_targets) if ocr_targets else []

            caption = (info.get("description") or "").strip()
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

    # --- Apify (image posts / carousels) --------------------------------

    @staticmethod
    def _image_urls(item: dict):
        urls = []
        for child in item.get("childPosts") or []:
            if child.get("type") != "Video" and child.get("displayUrl"):
                urls.append(child["displayUrl"])
        if not urls:
            for u in item.get("images") or []:
                if isinstance(u, str):
                    urls.append(u)
        if not urls and item.get("type") != "Video" and item.get("displayUrl"):
            urls.append(item["displayUrl"])
        return urls

    def _fetch_apify(self, url: str) -> Capture:
        if not APIFY_API_TOKEN:
            raise RuntimeError(
                "Image post detected, but APIFY_API_TOKEN is not configured "
                "(needed to fetch Instagram image carousels)."
            )
        from apify_client import ApifyClient

        client = ApifyClient(APIFY_API_TOKEN)
        run = client.actor("apify/instagram-scraper").call(
            run_input={"directUrls": [url], "resultsType": "posts", "resultsLimit": 1}
        )
        # apify-client 2.x returns a dict, 3.x returns a Run object
        dataset_id = run["defaultDatasetId"] if isinstance(run, dict) else run.default_dataset_id
        items = list(client.dataset(dataset_id).iterate_items())
        if not items:
            raise RuntimeError(f"Apify returned no data for {url}")
        item = items[0]

        shortcode = item.get("shortCode") or _shortcode(url)
        image_urls = self._image_urls(item)

        os.makedirs(TEMP_DIR, exist_ok=True)
        temp_files = []
        try:
            for idx, img_url in enumerate(image_urls):
                dst = os.path.join(TEMP_DIR, f"{shortcode}-apify-{idx:03d}.jpg")
                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
                        f.write(r.read())
                    temp_files.append(dst)
                except Exception:
                    continue

            ocr_blocks = ocr_images(temp_files) if temp_files else []

            caption = (item.get("caption") or "").strip()
            handle = item.get("ownerUsername") or "unknown"
            author = item.get("ownerFullName") or handle
            title = first_nonempty_line(caption) or f"Instagram Post {shortcode}"
            ts = item.get("timestamp") or ""
            published = ts[:10] if len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")

            # Instagram hides some counts -> Apify returns -1; omit those.
            metrics = {}
            if (item.get("likesCount") or -1) >= 0:
                metrics["likes"] = item["likesCount"]
            if (item.get("commentsCount") or -1) >= 0:
                metrics["comments"] = item["commentsCount"]

            return Capture(
                source="instagram",
                url=item.get("url") or url,
                source_id=shortcode,
                author=author,
                handle=handle,
                title=title,
                published=published,
                caption=caption,
                caption_heading="Caption",
                transcript_text="",
                transcript_language=None,
                ocr_blocks=ocr_blocks,
                metrics=metrics,
                tags=["instagram", "post", "inbox"],
            )
        finally:
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except OSError:
                    pass
