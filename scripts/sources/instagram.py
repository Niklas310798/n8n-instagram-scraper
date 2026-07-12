"""Instagram source adapter.

Primary path: yt-dlp (reels/videos) with a small retry for transient errors.
Fallback: Apify's instagram-scraper for anything yt-dlp can't deliver
(image posts, login-walled reels, empty responses). The Apify path handles
both videos (download -> transcribe + frame OCR) and image carousels (OCR),
capturing all metadata either way.
"""
import glob
import os
import time
import urllib.request
from datetime import datetime

import yt_dlp

from config import TEMP_DIR, APIFY_API_TOKEN
from errors import IngestError
from sources.base import Capture, Source, first_nonempty_line, published_from_ytdlp
from helpers.transcribe import transcribe_audio
from helpers.frames import extract_keyframes
from helpers.ocr import ocr_images

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_HARD_FAILS = ("login", "empty media", "private", "not available", "be accessible")


def _shortcode(url: str) -> str:
    parts = [p for p in url.split("?")[0].split("/") if p]
    for i, p in enumerate(parts):
        if p in ("reel", "reels", "p", "tv") and i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else "reel"


def _cleanup(paths):
    for f in paths or []:
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except OSError:
            pass


def _download(url: str, dst: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            f.write(r.read())
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


class InstagramSource(Source):
    name = "instagram"

    @staticmethod
    def matches(url: str) -> bool:
        return "instagram.com" in url.lower()

    def fetch(self, url: str) -> Capture:
        cap = self._fetch_ytdlp(url)
        if cap is not None:
            return cap
        return self._fetch_apify(url)

    # --- yt-dlp (reels / videos), with retry ----------------------------

    def _fetch_ytdlp(self, url: str, attempts: int = 2):
        shortcode = _shortcode(url)
        outtmpl = os.path.join(TEMP_DIR, f"{shortcode}.%(autonumber)03d.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl, "format": "best",
            "quiet": True, "no_warnings": True, "noplaylist": False,
        }
        os.makedirs(TEMP_DIR, exist_ok=True)

        for attempt in range(attempts):
            temp_files = []
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                files = sorted(glob.glob(os.path.join(TEMP_DIR, f"{shortcode}.*")))
                temp_files = list(files)
                video_path = next((f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS), None)
                image_paths = [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
                if not video_path and not image_paths:
                    return None  # image post -> Apify fallback

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
                    source="instagram", url=info.get("webpage_url") or url, source_id=shortcode,
                    author=author, handle=handle, title=title,
                    published=published_from_ytdlp(info), caption=caption, caption_heading="Caption",
                    transcript_text=(transcript.get("text") or "").strip(),
                    transcript_language=transcript.get("language"),
                    ocr_blocks=ocr_blocks, metrics=metrics, tags=["instagram", "reel", "inbox"],
                )
            except Exception as e:
                low = str(e).lower()
                if any(k in low for k in _HARD_FAILS) or attempt + 1 >= attempts:
                    return None  # give up -> Apify fallback
                time.sleep(2)
            finally:
                _cleanup(temp_files)
        return None

    # --- Apify (fallback: image posts + login-walled reels) -------------

    @staticmethod
    def _apify_meta(item: dict, url: str, shortcode: str):
        caption = (item.get("caption") or "").strip()
        handle = item.get("ownerUsername") or "unknown"
        ts = item.get("timestamp") or ""
        published = ts[:10] if len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")
        return {
            "url": item.get("url") or url,
            "source_id": shortcode,
            "caption": caption,
            "handle": handle,
            "author": item.get("ownerFullName") or handle,
            "title": first_nonempty_line(caption) or f"Instagram {shortcode}",
            "published": published,
        }

    @staticmethod
    def _counts(item: dict):
        metrics = {}
        if (item.get("likesCount") or -1) >= 0:
            metrics["likes"] = item["likesCount"]
        if (item.get("commentsCount") or -1) >= 0:
            metrics["comments"] = item["commentsCount"]
        return metrics

    @staticmethod
    def _image_urls(item: dict):
        urls = []
        for child in item.get("childPosts") or []:
            if child.get("type") != "Video" and child.get("displayUrl"):
                urls.append(child["displayUrl"])
        if not urls:
            urls = [u for u in (item.get("images") or []) if isinstance(u, str)]
        if not urls and item.get("type") != "Video" and item.get("displayUrl"):
            urls.append(item["displayUrl"])
        return urls

    def _fetch_apify(self, url: str) -> Capture:
        if not APIFY_API_TOKEN:
            raise IngestError("apify_not_configured",
                              "🔧 Bild-Post erkannt, aber Apify ist nicht konfiguriert.")
        from apify_client import ApifyClient

        client = ApifyClient(APIFY_API_TOKEN)
        run = client.actor("apify/instagram-scraper").call(
            run_input={"directUrls": [url], "resultsType": "posts", "resultsLimit": 1}
        )
        dataset_id = run["defaultDatasetId"] if isinstance(run, dict) else run.default_dataset_id
        items = list(client.dataset(dataset_id).iterate_items())
        if not items:
            raise IngestError("not_found",
                              "🚫 Für diesen Link konnten keine Inhalte gefunden werden (gelöscht oder privat?).")
        item = items[0]
        if item.get("error"):
            desc = item.get("errorDescription") or item.get("error")
            raise IngestError(
                "restricted",
                "🔒 Dieser Beitrag ist eingeschränkt (Alter/Region/Login) und konnte nicht abgerufen werden.",
                detail=f"apify: {item.get('error')} – {desc}")
        shortcode = item.get("shortCode") or _shortcode(url)
        meta = self._apify_meta(item, url, shortcode)
        metrics = self._counts(item)

        video_url = item.get("videoUrl") if (item.get("type") == "Video" or item.get("videoUrl")) else None
        if video_url:
            return self._apify_video(url, meta, metrics, item, video_url)
        return self._apify_images(meta, metrics, item)

    def _apify_video(self, url, meta, metrics, item, video_url) -> Capture:
        os.makedirs(TEMP_DIR, exist_ok=True)
        vpath = os.path.join(TEMP_DIR, f"{meta['source_id']}-apify.mp4")
        temp_files = [vpath]
        try:
            if not _download(video_url, vpath):
                raise IngestError("transient", "🔁 Video konnte nicht geladen werden. Bitte erneut senden.")
            transcript = transcribe_audio(vpath)
            frames = extract_keyframes(vpath, TEMP_DIR)
            temp_files += frames
            ocr_blocks = ocr_images(frames) if frames else []
            if item.get("videoPlayCount") is not None:
                metrics["views"] = item["videoPlayCount"]
            return Capture(
                source="instagram", url=meta["url"], source_id=meta["source_id"],
                author=meta["author"], handle=meta["handle"], title=meta["title"],
                published=meta["published"], caption=meta["caption"], caption_heading="Caption",
                transcript_text=(transcript.get("text") or "").strip(),
                transcript_language=transcript.get("language"),
                ocr_blocks=ocr_blocks, metrics=metrics, tags=["instagram", "reel", "inbox"],
            )
        finally:
            _cleanup(temp_files)

    def _apify_images(self, meta, metrics, item) -> Capture:
        os.makedirs(TEMP_DIR, exist_ok=True)
        temp_files = []
        try:
            for idx, img_url in enumerate(self._image_urls(item)):
                dst = os.path.join(TEMP_DIR, f"{meta['source_id']}-apify-{idx:03d}.jpg")
                if _download(img_url, dst):
                    temp_files.append(dst)
            ocr_blocks = ocr_images(temp_files) if temp_files else []
            return Capture(
                source="instagram", url=meta["url"], source_id=meta["source_id"],
                author=meta["author"], handle=meta["handle"], title=meta["title"],
                published=meta["published"], caption=meta["caption"], caption_heading="Caption",
                transcript_text="", transcript_language=None,
                ocr_blocks=ocr_blocks, metrics=metrics, tags=["instagram", "post", "inbox"],
            )
        finally:
            _cleanup(temp_files)
