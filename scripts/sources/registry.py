"""URL -> Source resolution. Register new adapters here."""
from sources.base import Source
from sources.instagram import InstagramSource
from sources.youtube import YouTubeSource

SOURCES = [
    InstagramSource(),
    YouTubeSource(),
]


def resolve(url: str) -> Source:
    for source in SOURCES:
        if source.matches(url):
            return source
    raise ValueError(f"No source adapter matches URL: {url}")
