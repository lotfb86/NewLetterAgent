"""Tests for services.rss_reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from models import Confidence, SourceTier
from services.rss_reader import FeedSource, RSSReader


def test_collect_recent_stories_filters_old_and_dedupes(app_config: Any, monkeypatch: Any) -> None:
    now = datetime(2026, 2, 27, tzinfo=UTC)

    source = FeedSource(
        name="Test Feed",
        url="https://example.com/feed.xml",
        source_tier=SourceTier.TIER_1,
        default_confidence=Confidence.MEDIUM,
    )
    reader = RSSReader(app_config, feed_sources=(source,))

    recent = now.timetuple()
    old = (now - timedelta(days=30)).timetuple()

    fake_entries = [
        SimpleNamespace(
            title="Recent Story",
            link="https://example.com/a",
            published_parsed=recent,
            summary="summary",
        ),
        SimpleNamespace(
            title="Old Story",
            link="https://example.com/b",
            published_parsed=old,
            summary="old",
        ),
        SimpleNamespace(
            title="Recent Story Duplicate",
            link="https://example.com/a/",
            published_parsed=recent,
            summary="dup",
        ),
    ]

    class _FakeResponse:
        content = b"xml"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(*_: Any, **__: Any) -> _FakeResponse:
        return _FakeResponse()

    monkeypatch.setattr(requests, "get", _fake_get)
    monkeypatch.setattr(
        "services.rss_reader.feedparser.parse",
        lambda _: SimpleNamespace(entries=fake_entries),
    )

    stories = reader.collect_recent_stories(lookback_days=7, now=now)

    assert len(stories) == 1
    assert stories[0].title == "Recent Story"


def test_collect_recent_stories_raises_when_all_sources_fail(
    app_config: Any,
    monkeypatch: Any,
) -> None:
    source = FeedSource(
        name="Fail Feed",
        url="https://example.com/feed.xml",
        source_tier=SourceTier.TIER_1,
        default_confidence=Confidence.MEDIUM,
    )
    reader = RSSReader(app_config, feed_sources=(source,))

    def _fake_get(*_: Any, **__: Any) -> Any:
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "get", _fake_get)

    with pytest.raises(Exception) as exc_info:
        reader.collect_recent_stories()

    assert "All RSS sources failed" in str(exc_info.value)
