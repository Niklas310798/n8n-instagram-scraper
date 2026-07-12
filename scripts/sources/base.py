"""Source-adapter foundations.

A `Source` knows how to recognize its URLs and turn one into a normalized
`Capture`. The rest of the pipeline (markdown rendering, writing to the vault)
is source-agnostic and works off `Capture` alone — so adding a new platform
means adding one file under `sources/`.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Capture:
    """Normalized result of ingesting one piece of content."""
    source: str                       # "instagram", "youtube", ...
    url: str
    source_id: str                    # shortcode / video id (used in filename)
    author: str = "unknown"           # display name (frontmatter `author`)
    handle: str = "unknown"           # @handle / channel slug (folder + frontmatter `handle`)
    title: Optional[str] = None
    published: Optional[str] = None    # YYYY-MM-DD
    caption: str = ""                  # caption / description text
    caption_heading: str = "Caption"   # heading used for the caption section
    transcript_text: str = ""
    transcript_language: Optional[str] = None
    ocr_blocks: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)        # ordered -> frontmatter lines
    extra_sections: List[Tuple[str, str]] = field(default_factory=list)  # (heading, body)
    tags: List[str] = field(default_factory=list)


class Source:
    """Base class for a content source adapter."""
    name: str = "source"

    @staticmethod
    def matches(url: str) -> bool:
        raise NotImplementedError

    def fetch(self, url: str) -> Capture:
        raise NotImplementedError


# --- shared helpers -------------------------------------------------------

def first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def slugify(text: str, maxlen: int = 60) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:maxlen].strip("-") or "unknown"


def published_from_ytdlp(info: Dict[str, Any]) -> str:
    """Derive a YYYY-MM-DD date from a yt-dlp info dict."""
    ud = info.get("upload_date")
    if ud and len(ud) == 8:
        return f"{ud[0:4]}-{ud[4:6]}-{ud[6:8]}"
    ts = info.get("timestamp")
    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")
