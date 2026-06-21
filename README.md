# Instagram → Markdown Capture (Second-Brain Ingest)

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-green)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Turn any Instagram reel or post into a clean, **LLM-optimized Markdown file** and drop it
into your local knowledge vault (Obsidian, an LLM wiki, plain folder — anything file-based).

It is built as a **capture adapter**: it extracts the content *faithfully* and leaves the
summarizing, tagging and cross-linking to your downstream tool (e.g. an LLM that reads your
vault). Send a link, get a source document — caption, on-screen text, and spoken transcript,
grouped per creator.

> Send a Telegram message with a reel link → a few seconds later a Markdown file appears in
> `raw/instagram/<handle>/`, ready for your "second brain".

## What it captures

For each reel/post, one Markdown file with light YAML frontmatter and three content layers:

| Layer | Source | How |
|-------|--------|-----|
| **Caption + metadata** | the post | yt-dlp (author, handle, date, likes/views, URL) |
| **On-screen text** | video frames / carousel images | ffmpeg scene-change keyframes → RapidOCR (deduplicated) |
| **Spoken transcript** | audio track | Whisper (local `faster-whisper`, or OpenAI API) |

Image-only posts skip the transcript; talking-head reels without on-screen text skip OCR.
The downloaded media is processed and then deleted — only the Markdown is kept.

### Example output

```markdown
---
title: "The 5 skills that will run the future"
type: source
source: instagram
url: https://www.instagram.com/reels/XXXX/
author: "Callum Carver"
handle: callumcarver
published: 2026-06-20
captured: 2026-06-21
likes: 269
language: en
tags: [instagram, reel, inbox]
---

# The 5 skills that will run the future

## Caption
...
## On-screen text
5 AI skills that will pay you $20,000/month
## Transcript
...
```

## Architecture

```
(optional) Telegram bot ──► n8n (via ngrok) ──► POST /n8n/ingest {url}
                                                       │
                       ┌──────────── FastAPI (Docker) ────────────┐
                       │ 1. yt-dlp    → caption + metadata + media │
                       │ 2. Whisper   → transcript                 │
                       │ 3. ffmpeg+OCR → on-screen text            │
                       │ 4. render Markdown                        │
                       │ 5. write → <vault>/raw/instagram/<handle>/ │
                       └────────────────────────────────────────────┘
```

The core is a single FastAPI service. The Telegram + n8n layer is **optional** — you can call
the HTTP endpoint directly from a script, a cron job, or any automation tool.

### Repository layout

```
scripts/
  main.py                  FastAPI app (+ /health)
  config.py                env-driven settings
  api/instagram_routes.py  POST /n8n/ingest
  helpers/
    scrapper.py            yt-dlp: media + metadata
    transcribe.py          faster-whisper / OpenAI whisper
    frames.py              ffmpeg scene-change keyframes
    ocr.py                 RapidOCR on-screen text
    markdown.py            render + write the raw/ document
Dockerfile / docker-compose.yml
requirements.txt
.env.example
n8n_telegram_capture.json  importable n8n workflow (Telegram trigger)
```

## Initial setup

**Prerequisites:** Docker + Docker Compose. (ffmpeg, yt-dlp, Whisper and RapidOCR all run
inside the container — nothing else to install.)

1. Clone and configure:
   ```bash
   git clone <your-fork-url>
   cd instagram-markdown-capture
   cp .env.example .env
   ```
2. Edit `.env` — set `VAULT_HOST_PATH` to the absolute path of your vault's `raw/` folder.
   Pick `WHISPER_MODEL` (`base` is a good default; `small`/`medium` are more accurate).
3. Build and run:
   ```bash
   docker compose up --build -d
   ```
   The first ingest downloads the Whisper + OCR models once (cached afterwards).
4. Test it:
   ```bash
   curl -X POST http://localhost:8000/n8n/ingest \
     -H "Content-Type: application/json" \
     -d '{"url":"https://www.instagram.com/reels/XXXX/"}'
   ```
   A `.md` file should appear in `<your-vault>/raw/instagram/<handle>/`.

### Optional: Telegram trigger via n8n

Capture links from your phone by sending them to a Telegram bot.

1. Create a bot with [@BotFather](https://t.me/botfather) and copy the token.
2. Expose your n8n to the internet so Telegram can reach it (e.g. `ngrok http 5678`,
   ideally with a static domain) and set n8n's `WEBHOOK_URL` to that public URL.
3. In n8n, import `n8n_telegram_capture.json`, assign your Telegram credential to both
   Telegram nodes, and activate the workflow.
4. Send a reel link to your bot. The workflow:
   `Telegram trigger → instant "processing…" reply → POST /n8n/ingest → "✅ saved" reply`.

> If n8n runs in Docker, it reaches the API container at `http://host.docker.internal:8000`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_HOST_PATH` | – | Host path to your vault's `raw/` folder (bind-mounted into the container) |
| `INSTAGRAM_SUBDIR` | `instagram` | Subfolder inside `raw/`; files are written to `<sub>/<handle>/` |
| `WHISPER_MODE` | `LOCAL` | `LOCAL` (faster-whisper) or `API` (OpenAI) |
| `WHISPER_MODEL` | `base` | `tiny`/`base`/`small`/`medium`/`large-v3` |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type (`int8`, `float32`, …) |
| `WHISPER_API_KEY` | – | OpenAI key, only when `WHISPER_MODE=API` |

## API

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/n8n/ingest` | POST | `{"url": "<instagram-url>"}` | Capture one reel/post → write Markdown, return a summary |
| `/health` | GET | – | Liveness check |

## Roadmap

- [ ] Strip tracking params (`?igsh=…`) from captured URLs
- [ ] Account monitoring: scheduled batch capture of a creator's latest reels
- [ ] Optional auto-ingest hook (trigger a downstream LLM after capture)
- [ ] Lighter image / ARM build for Raspberry Pi
- [ ] Better OCR cleanup (drop UI chrome, merge fragmented text)

## Contributing

Contributions are very welcome — this is an early, focused tool and there is plenty of low-
hanging fruit (see the roadmap). To get involved:

1. Fork the repo and create a feature branch.
2. Keep changes small and focused; match the existing style.
3. Open a pull request describing the change and how you tested it.

Bug reports, ideas and "it didn't work for this reel" issues are equally useful — please open
an issue with the URL (if shareable) and the error.

## Notes & limits

- Works with **public** reels/posts. Private or age-gated content may require yt-dlp cookies.
- Respect Instagram's Terms of Service and creators' rights; use for personal knowledge capture.

## Credits

Repurposed from an earlier Instagram automation project; the pipeline has been rebuilt around
local, file-based knowledge capture. Licensed under the **MIT License** — see `LICENSE`.
