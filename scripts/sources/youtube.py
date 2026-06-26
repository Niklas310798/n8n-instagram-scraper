"""YouTube source adapter.

Transcript strategy: prefer existing subtitles (manual > automatic) via yt-dlp —
instant and free — and only fall back to Whisper when none are available.
On-screen-text OCR is off by default (long videos, low value); enable with
YOUTUBE_OCR=true.
"""
import glob
import os
import re
import urllib.parse
import urllib.request

import yt_dlp

from config import TEMP_DIR, YOUTUBE_OCR
from sources.base import Capture, Source, published_from_ytdlp
from helpers.transcribe import transcribe_audio

_PREFERRED_LANGS = ["en", "en-US", "en-GB", "en-orig"]


def _video_id(url: str) -> str:
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0].split("/")[0]
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    parts = [p for p in parsed.path.split("/") if p]
    for key in ("shorts", "embed", "v"):
        if key in parts:
            i = parts.index(key)
            if i + 1 < len(parts):
                return parts[i + 1]
    return parts[-1] if parts else "video"


def _fmt_ts(seconds) -> str:
    s = int(seconds or 0)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _clean_vtt(raw: str) -> str:
    """Turn a WebVTT subtitle file into plain text."""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.isdigit():
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()  # drop <00:..> and <c> tags
        if not line or (out and out[-1] == line):     # collapse rolling duplicates
            continue
        out.append(line)
    return "\n".join(out)


def _pick_track(tracks: dict, lang):
    if not tracks:
        return None
    for cand in ([lang] if lang else []) + _PREFERRED_LANGS:
        if cand in tracks:
            entries = tracks[cand]
            return next((e for e in entries if e.get("ext") == "vtt"), entries[0])
    first = next(iter(tracks.values()))
    return next((e for e in first if e.get("ext") == "vtt"), first[0])


class YouTubeSource(Source):
    name = "youtube"

    @staticmethod
    def matches(url: str) -> bool:
        u = url.lower()
        return "youtube.com" in u or "youtu.be" in u

    def fetch(self, url: str) -> Capture:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        transcript_text, language = self._subtitles(info)
        if not transcript_text:
            transcript_text, language = self._whisper_fallback(url, info)

        ocr_blocks = self._ocr(url, info) if YOUTUBE_OCR else []

        author = info.get("channel") or info.get("uploader") or "unknown"
        # uploader_id is like "@jawed"; strip the @ so it isn't doubled / invalid YAML
        handle = (info.get("uploader_id") or info.get("channel_id") or author).lstrip("@")

        metrics = {}
        if info.get("view_count") is not None:
            metrics["views"] = info["view_count"]
        if info.get("like_count") is not None:
            metrics["likes"] = info["like_count"]

        extra = []
        chapters = info.get("chapters") or []
        if chapters:
            body = "\n".join(
                f"- {_fmt_ts(c.get('start_time'))} {c.get('title', '')}".rstrip()
                for c in chapters
            )
            extra.append(("Chapters", body))

        return Capture(
            source="youtube",
            url=info.get("webpage_url") or url,
            source_id=info.get("id") or _video_id(url),
            author=author,
            handle=handle,
            title=info.get("title"),
            published=published_from_ytdlp(info),
            caption=(info.get("description") or "").strip(),
            caption_heading="Description",
            transcript_text=transcript_text,
            transcript_language=language,
            ocr_blocks=ocr_blocks,
            metrics=metrics,
            extra_sections=extra,
            tags=["youtube", "video", "inbox"],
        )

    # --- transcript sources ---------------------------------------------

    def _subtitles(self, info):
        """Return (text, language) from manual subs, else automatic captions."""
        lang = info.get("language")
        for store in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
            track = _pick_track(store, lang)
            if not track or not track.get("url"):
                continue
            try:
                with urllib.request.urlopen(track["url"], timeout=30) as r:
                    raw = r.read().decode("utf-8", "replace")
                text = _clean_vtt(raw)
                if text.strip():
                    return text, (lang or "en")
            except Exception:
                continue
        return "", None

    def _whisper_fallback(self, url, info):
        vid = info.get("id") or _video_id(url)
        base = os.path.join(TEMP_DIR, f"yt-{vid}")
        opts = {
            "outtmpl": base + ".%(ext)s",
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            "quiet": True, "no_warnings": True, "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            audio = base + ".wav"
            if os.path.exists(audio):
                t = transcribe_audio(audio)
                return (t.get("text") or "").strip(), t.get("language")
            return "", None
        finally:
            for f in glob.glob(base + "*"):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # --- optional OCR ----------------------------------------------------

    def _ocr(self, url, info):
        from helpers.frames import extract_keyframes
        from helpers.ocr import ocr_images
        vid = info.get("id") or _video_id(url)
        base = os.path.join(TEMP_DIR, f"yt-ocr-{vid}")
        opts = {"outtmpl": base + ".%(ext)s", "format": "best",
                "quiet": True, "no_warnings": True, "noplaylist": True}
        files = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            vids = glob.glob(base + ".*")
            if not vids:
                return []
            files = list(vids)
            frames = extract_keyframes(vids[0], TEMP_DIR)
            files += frames
            return ocr_images(frames) if frames else []
        except Exception:
            return []
        finally:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass
