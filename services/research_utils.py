"""Shared utilities for research source adapters."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from models import StoryCandidate

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_URL_PATTERN = re.compile(r"https?://[^\s)\"'>]+")


def extract_markdown_link_titles(content: str) -> dict[str, str]:
    """Map URL → title from markdown-style links in content."""
    matches = _MARKDOWN_LINK.findall(content)
    return {url.strip(): title.strip() for title, url in matches}


def extract_urls(content: str) -> list[str]:
    """Extract unique URLs in order of appearance."""
    raw = _URL_PATTERN.findall(content)
    cleaned = [url.rstrip(".,;:") for url in raw]
    return list(dict.fromkeys(cleaned))


def source_name_from_url(url: str) -> str:
    """Derive a short source label from a URL host."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "external-source"


def fallback_title(url: str) -> str:
    """Best-effort title from the URL path when no title is available."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return source_name_from_url(url)
    last = path.split("/")[-1].replace("-", " ").replace("_", " ").strip()
    return last.title() if last else source_name_from_url(url)


def dedupe_by_url(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    """Simple URL-based dedup within a single source adapter."""
    seen: set[str] = set()
    deduped: list[StoryCandidate] = []
    for story in stories:
        url = story.source_url.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        deduped.append(story)
    return deduped
