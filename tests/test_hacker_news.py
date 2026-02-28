"""Tests for Hacker News adapter."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import requests

from services.hacker_news import HackerNewsReader


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def test_hacker_news_reader_normalizes_stories(app_config: Any, monkeypatch: Any) -> None:
    reader = HackerNewsReader(app_config)

    def _fake_get(url: str, **_: Any) -> _FakeResponse:
        if "topstories" in url:
            return _FakeResponse([1001])
        return _FakeResponse(
            {
                "id": 1001,
                "title": "HN Story",
                "url": "https://example.com/story",
                "time": 1_700_000_000,
            }
        )

    monkeypatch.setattr(requests, "get", _fake_get)

    stories = reader.fetch_top_stories(max_items=5)

    assert len(stories) == 1
    assert stories[0].title == "HN Story"
    assert stories[0].published_at is not None
    assert stories[0].published_at.tzinfo == UTC
