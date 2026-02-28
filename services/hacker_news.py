"""Hacker News top stories adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import requests

from config import AppConfig
from models import Confidence, SourceTier, StoryCandidate
from services.resilience import ResiliencePolicy

HACKER_NEWS_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HACKER_NEWS_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


class HackerNewsReader:
    """Fetch and normalize Hacker News top stories."""

    def __init__(
        self,
        config: AppConfig,
        *,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self._request_timeout_seconds = request_timeout_seconds
        self._resilience = ResiliencePolicy(
            name="hacker_news",
            max_attempts=config.max_external_retries,
        )

    def fetch_top_stories(self, *, max_items: int = 20) -> list[StoryCandidate]:
        """Fetch top story IDs and return normalized story objects."""

        def _fetch_ids() -> requests.Response:
            response = requests.get(
                HACKER_NEWS_TOPSTORIES_URL,
                timeout=self._request_timeout_seconds,
            )
            response.raise_for_status()
            return response

        ids_response = self._resilience.execute(_fetch_ids)
        ids_payload = ids_response.json()
        if not isinstance(ids_payload, list):
            return []

        valid_ids = [i for i in ids_payload[:max_items] if isinstance(i, int)]
        stories: list[StoryCandidate] = []

        with ThreadPoolExecutor(max_workers=10) as pool:
            future_map = {pool.submit(self._fetch_item, i): i for i in valid_ids}
            for future in as_completed(future_map):
                story = future.result()
                if story is not None:
                    stories.append(story)

        return stories

    def _fetch_item(self, item_id: int) -> StoryCandidate | None:
        def _operation() -> requests.Response:
            response = requests.get(
                HACKER_NEWS_ITEM_URL.format(id=item_id),
                timeout=self._request_timeout_seconds,
            )
            response.raise_for_status()
            return response

        response = self._resilience.execute(_operation)
        payload = response.json()
        if not isinstance(payload, dict):
            return None

        title = str(payload.get("title", "")).strip()
        if not title:
            return None

        url = str(payload.get("url") or f"https://news.ycombinator.com/item?id={item_id}").strip()

        timestamp = payload.get("time")
        published_at = None
        if isinstance(timestamp, int):
            published_at = datetime.fromtimestamp(timestamp, tz=UTC)

        return StoryCandidate(
            title=title,
            source_url=url,
            source_name="Hacker News",
            published_at=published_at,
            confidence=Confidence.LOW,
            source_tier=SourceTier.TIER_3,
            summary=None,
            metadata={"hn_id": item_id},
        )
