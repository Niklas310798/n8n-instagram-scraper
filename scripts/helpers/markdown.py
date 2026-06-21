"""Render an Instagram reel into a raw/ source document for the wiki.

This deliberately produces a *faithful* capture (light frontmatter + caption +
transcript). It does NOT summarise, tag or cross-link — that is the job of the
wiki's Ingest workflow (Claude Code), which reads raw/ and writes wiki/sources/.
"""
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict
from config import VAULT_RAW_DIR, INSTAGRAM_SUBDIR


def _slugify(text: str, maxlen: int = 60) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "reel"


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _yaml_escape(text: str) -> str:
    return (text or "").replace('"', "'").strip()


def _published_date(meta: Dict[str, Any]) -> str:
    ud = meta.get("upload_date")
    if ud and len(ud) == 8:
        return f"{ud[0:4]}-{ud[4:6]}-{ud[6:8]}"
    ts = meta.get("timestamp")
    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def build_markdown(meta: Dict[str, Any], transcript: Dict[str, Any],
                   ocr_blocks: list = None) -> str:
    published = _published_date(meta)
    handle = meta.get("uploader_handle") or meta.get("uploader") or "unknown"
    author = meta.get("uploader") or handle
    caption = (meta.get("caption") or "").strip()
    title = _first_line(caption) or meta.get("title") or f"Instagram Reel {meta.get('shortcode')}"

    fm = [
        "---",
        f'title: "{_yaml_escape(title)}"',
        "type: source",
        "source: instagram",
        f"url: {meta.get('url')}",
        f'author: "{_yaml_escape(author)}"',
        f"handle: {handle}",
        f"published: {published}",
        f"captured: {datetime.now().strftime('%Y-%m-%d')}",
    ]
    if meta.get("view_count") is not None:
        fm.append(f"views: {meta['view_count']}")
    if meta.get("like_count") is not None:
        fm.append(f"likes: {meta['like_count']}")
    if transcript.get("language"):
        fm.append(f"language: {transcript['language']}")
    fm.append("tags: [instagram, reel, inbox]")
    fm.append("---")

    text = (transcript.get("text") or "").strip()
    body = [
        f"# {title}",
        "",
        f"**Source:** {meta.get('url')} — {author} (@{handle}) · {published}",
        "",
    ]
    if caption:
        body += ["## Caption", "", caption, ""]
    if ocr_blocks:
        body += ["## On-screen text", ""]
        for block in ocr_blocks:
            body += [block, ""]
    body += ["## Transcript", "", text if text else "_(no speech detected)_", ""]

    return "\n".join(fm) + "\n\n" + "\n".join(body)


def write_raw_file(meta: Dict[str, Any], content: str) -> str:
    # One folder per creator handle so transcripts are grouped by author.
    handle = _slugify(meta.get("uploader_handle") or meta.get("uploader") or "unknown", 30)
    out_dir = os.path.join(VAULT_RAW_DIR, INSTAGRAM_SUBDIR, handle)
    os.makedirs(out_dir, exist_ok=True)
    published = _published_date(meta)
    shortcode = meta.get("shortcode") or "reel"
    filename = f"{published}-{shortcode}.md"
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
