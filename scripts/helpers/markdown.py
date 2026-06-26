"""Render a normalized Capture into a raw/ source document and write it.

Source-agnostic: it only reads a `Capture`. The output stays a *faithful*
capture (frontmatter + caption + on-screen text + transcript); summarizing,
tagging and cross-linking is the job of the downstream wiki ingest.
"""
import os
from datetime import datetime

from config import VAULT_RAW_DIR, INSTAGRAM_SUBDIR
from sources.base import Capture, slugify


def _yaml_escape(text: str) -> str:
    return (text or "").replace('"', "'").strip()


def _subdir_for(source: str) -> str:
    # Keep Instagram's existing (configurable) folder; others use their name.
    return INSTAGRAM_SUBDIR if source == "instagram" else source


def render_capture(cap: Capture) -> str:
    title = cap.title or cap.source_id

    fm = [
        "---",
        f'title: "{_yaml_escape(title)}"',
        "type: source",
        f"source: {cap.source}",
        f"url: {cap.url}",
        f'author: "{_yaml_escape(cap.author)}"',
        f"handle: {cap.handle}",
        f"published: {cap.published}",
        f"captured: {datetime.now().strftime('%Y-%m-%d')}",
    ]
    for key, value in cap.metrics.items():
        fm.append(f"{key}: {value}")
    if cap.transcript_language:
        fm.append(f"language: {cap.transcript_language}")
    fm.append("tags: [" + ", ".join(cap.tags) + "]")
    fm.append("---")

    body = [
        f"# {title}",
        "",
        f"**Source:** {cap.url} — {cap.author} (@{cap.handle}) · {cap.published}",
        "",
    ]
    if cap.caption:
        body += [f"## {cap.caption_heading}", "", cap.caption, ""]
    for heading, content in cap.extra_sections:
        body += [f"## {heading}", "", content, ""]
    if cap.ocr_blocks:
        body += ["## On-screen text", ""]
        for block in cap.ocr_blocks:
            body += [block, ""]
    body += ["## Transcript", "",
             cap.transcript_text if cap.transcript_text else "_(no speech detected)_", ""]

    return "\n".join(fm) + "\n\n" + "\n".join(body)


def write_capture(cap: Capture) -> str:
    """Render and write the capture to <vault>/raw/<source>/<handle>/<date>-<id>.md."""
    content = render_capture(cap)
    handle = slugify(cap.handle or cap.author or "unknown", 30)
    out_dir = os.path.join(VAULT_RAW_DIR, _subdir_for(cap.source), handle)
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{cap.published}-{cap.source_id}.md"
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
