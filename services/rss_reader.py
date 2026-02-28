"""RSS source fetch and normalization service."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import struct_time
from typing import Any

import feedparser
import requests

logger = logging.getLogger(__name__)

from config import AppConfig
from models import Confidence, SourceTier, StoryCandidate
from services.resilience import ExternalServiceError, ResiliencePolicy


@dataclass(frozen=True)
class FeedSource:
    """Definition of an RSS feed source."""

    name: str
    url: str
    source_tier: SourceTier
    default_confidence: Confidence


DEFAULT_FEED_SOURCES: tuple[FeedSource, ...] = (
    FeedSource(
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        source_tier=SourceTier.TIER_2,
        default_confidence=Confidence.MEDIUM,
    ),
    FeedSource(
        name="VentureBeat AI",
        url="https://venturebeat.com/category/ai/feed/",
        source_tier=SourceTier.TIER_2,
        default_confidence=Confidence.MEDIUM,
    ),
    FeedSource(
        name="Crunchbase News",
        url="https://news.crunchbase.com/feed/",
        source_tier=SourceTier.TIER_2,
        default_confidence=Confidence.MEDIUM,
    ),
    FeedSource(
        name="Wes Roth (NATURAL 20)",
        url="https://rss.beehiiv.com/feeds/uCpOrhb7xR.xml",
        source_tier=SourceTier.TIER_3,
        default_confidence=Confidence.LOW,
    ),
    FeedSource(
        name="Google News RSS",
        url="https://news.google.com/rss/search?q=AI+agents+digital+labor+funding",
        source_tier=SourceTier.TIER_3,
        default_confidence=Confidence.LOW,
    ),
    FeedSource(
        name="OpenAI Blog",
        url="https://openai.com/blog/rss.xml",
        source_tier=SourceTier.TIER_1,
        default_confidence=Confidence.HIGH,
    ),
    FeedSource(
        name="Anthropic Blog",
        url="https://www.anthropic.com/research/rss.xml",
        source_tier=SourceTier.TIER_1,
        default_confidence=Confidence.HIGH,
    ),
)


class RSSReader:
    """Read and normalize stories from configured RSS feed sources."""

    def __init__(
        self,
        config: AppConfig,
        *,
        feed_sources: tuple[FeedSource, ...] = DEFAULT_FEED_SOURCES,
        request_timeout_seconds: float = 15.0,
        max_workers: int = 8,
    ) -> None:
        self._config = config
        self._feed_sources = feed_sources
        self._request_timeout_seconds = request_timeout_seconds
        self._max_workers = max_workers
        self._resilience = ResiliencePolicy(
            name="rss_fetch",
            max_attempts=config.max_external_retries,
        )

    def collect_recent_stories(
        self,
        *,
        lookback_days: int = 7,
        now: datetime | None = None,
    ) -> list[StoryCandidate]:
        """Fetch configured feeds in parallel and return normalized recent stories."""
        now_utc = now.astimezone(UTC) if now else datetime.now(UTC)
        earliest = now_utc - timedelta(days=lookback_days)

        collected: list[StoryCandidate] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_map = {
                pool.submit(self._read_source, source): source for source in self._feed_sources
            }
            for future in as_completed(future_map):
                source = future_map[future]
                try:
                    stories = future.result()
                except ExternalServiceError as exc:
                    errors.append(f"{source.name}: {exc}")
                    continue

                for story in stories:
                    if story.published_at is not None and story.published_at < earliest:
                        continue
                    collected.append(story)

        for err in errors:
            logger.warning("RSS feed error: %s", err)

        if errors and not collected:
            raise ExternalServiceError("All RSS sources failed: " + "; ".join(errors))

        return _dedupe_by_url(collected)

    def _read_source(self, source: FeedSource) -> list[StoryCandidate]:
        def _operation() -> requests.Response:
            response = requests.get(source.url, timeout=self._request_timeout_seconds)
            response.raise_for_status()
            return response

        response = self._resilience.execute(_operation)
        parsed = feedparser.parse(response.content)

        stories: list[StoryCandidate] = []
        for entry in parsed.entries:
            story = _entry_to_story(entry=entry, source=source)
            if story is None:
                continue
            stories.append(story)

        return stories


def _entry_to_story(*, entry: Any, source: FeedSource) -> StoryCandidate | None:
    title = str(getattr(entry, "title", "")).strip()
    url = str(getattr(entry, "link", "")).strip()
    if not title or not url:
        return None

    published_at = _extract_entry_datetime(entry)
    summary = str(getattr(entry, "summary", "")).strip() or None

    return StoryCandidate(
        title=title,
        source_url=url,
        source_name=source.name,
        published_at=published_at,
        confidence=source.default_confidence,
        source_tier=source.source_tier,
        summary=summary,
    )


def _extract_entry_datetime(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed is None:
            continue
        if isinstance(parsed, struct_time):
            return datetime(
                parsed.tm_year,
                parsed.tm_mon,
                parsed.tm_mday,
                parsed.tm_hour,
                parsed.tm_min,
                parsed.tm_sec,
                tzinfo=UTC,
            )
        if isinstance(parsed, tuple) and len(parsed) >= 6:
            return datetime(
                int(parsed[0]),
                int(parsed[1]),
                int(parsed[2]),
                int(parsed[3]),
                int(parsed[4]),
                int(parsed[5]),
                tzinfo=UTC,
            )
    return None


def _dedupe_by_url(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    seen: set[str] = set()
    deduped: list[StoryCandidate] = []

    for story in stories:
        normalized = story.source_url.strip().rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(story)

    return deduped
