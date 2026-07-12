#!/usr/bin/env python3
"""Convert PDFs dropped into <vault>/raw/pdf-inbox/ into Markdown source docs.

Runs on the host (cron), not in the container. For each PDF in the inbox:
  - extract Markdown with pymupdf4llm (headings, tables, reading order)
  - write <vault>/raw/pdf/<slug>.md with light frontmatter
  - move the original next to it (<vault>/raw/pdf/<slug>.pdf) — raw/ keeps
    the immutable source, the .md is what the nightly wiki ingest consumes
  - send a short Telegram summary (token file: ~/.telegram-notify)

The vault sync cron commits raw/ changes; the nightly Claude ingest picks up
the new .md files and does the summarizing/linking into wiki/.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf4llm

VAULT = Path(os.environ.get("VAULT_DIR", "/home/niklas/myssd/projects/schwinglab-wiki"))
INBOX = VAULT / "raw" / "pdf-inbox"
OUTDIR = VAULT / "raw" / "pdf"


def slugify(text: str, maxlen: int = 70) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "document"


def yaml_escape(text: str) -> str:
    return (text or "").replace('"', "'").strip()


def notify(text: str) -> None:
    try:
        envfile = Path.home() / ".telegram-notify"
        env = dict(l.strip().split("=", 1) for l in envfile.read_text().splitlines() if "=" in l)
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % env["TG_TOKEN"],
            data=json.dumps({"chat_id": env["TG_CHAT"], "text": text}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print("notify failed:", e)


def convert(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    pages = doc.page_count
    title = (meta.get("title") or "").strip() or pdf_path.stem.replace("_", " ").replace("-", " ").strip()
    author = (meta.get("author") or "").strip()
    doc.close()

    body = pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)

    slug = slugify(title)
    md_path = OUTDIR / f"{slug}.md"
    pdf_dest = OUTDIR / f"{slug}.pdf"
    n = 2
    while md_path.exists() or pdf_dest.exists():   # avoid collisions
        md_path = OUTDIR / f"{slug}-{n}.md"
        pdf_dest = OUTDIR / f"{slug}-{n}.pdf"
        n += 1

    fm = [
        "---",
        f'title: "{yaml_escape(title)}"',
        "type: source",
        "source: pdf",
    ]
    if author:
        fm.append(f'author: "{yaml_escape(author)}"')
    fm += [
        f"pages: {pages}",
        f"original: ./{pdf_dest.name}",
        f"captured: {date.today().isoformat()}",
        "tags: [pdf, document, inbox]",
        "---",
    ]

    md_path.write_text("\n".join(fm) + "\n\n" + body, encoding="utf-8")
    pdf_path.rename(pdf_dest)
    return f"{title} ({pages} S.) -> raw/pdf/{md_path.name}"


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(p for p in INBOX.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        return
    done, failed = [], []
    for pdf in pdfs:
        try:
            done.append(convert(pdf))
        except Exception as e:
            failed.append(f"{pdf.name}: {e}")
            print(f"FEHLER {pdf.name}: {e}", file=sys.stderr)
    if done:
        print("\n".join(done))
        msg = "📄 %d PDF(s) zu Markdown konvertiert:\n%s" % (len(done), "\n".join(done))
        if failed:
            msg += "\n⚠️ Fehlgeschlagen:\n" + "\n".join(failed)
        msg += "\nWiki-Einarbeitung heute Nacht um 03:30."
        notify(msg)
    elif failed:
        notify("⚠️ PDF-Konvertierung fehlgeschlagen:\n" + "\n".join(failed))


if __name__ == "__main__":
    main()
