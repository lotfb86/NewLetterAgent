"""Tests for services.quality."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from models import Confidence, SourceTier, StoryCandidate
from services.quality import (
    apply_canonicalization_and_tiering,
    assign_source_tier,
    canonicalize_url,
    enforce_numeric_claim_verification,
    enforce_recency,
    to_planning_inputs,
    validate_citation_fields,
)


def _story(
    *,
    title: str,
    url: str,
    source_name: str = "Source",
    published_at: datetime | None = None,
    confidence: Confidence = Confidence.MEDIUM,
    source_tier: SourceTier = SourceTier.TIER_2,
    summary: str | None = None,
) -> StoryCandidate:
    return StoryCandidate(
        title=title,
        source_url=url,
        source_name=source_name,
        published_at=published_at,
        confidence=confidence,
        source_tier=source_tier,
        summary=summary,
    )


def test_canonicalize_url_removes_tracking_params() -> None:
    raw = "https://www.example.com/path/?utm_source=x&ref=abc&id=1"
    normalized = canonicalize_url(raw)

    assert normalized == "https://example.com/path?id=1"


def test_assign_source_tier_for_known_domains() -> None:
    assert assign_source_tier("https://openai.com/blog") == SourceTier.TIER_1
    assert assign_source_tier("https://techcrunch.com/x") == SourceTier.TIER_2
    assert assign_source_tier("https://random-substack.com/y") == SourceTier.TIER_3


def test_apply_canonicalization_and_tiering_updates_fields() -> None:
    stories = [
        _story(title="Story", url="https://www.openai.com/blog/?utm_medium=email"),
    ]

    output = apply_canonicalization_and_tiering(stories)

    assert output[0].source_url == "https://openai.com/blog"
    assert output[0].source_tier == SourceTier.TIER_1
    assert output[0].confidence == Confidence.HIGH


def test_numeric_claim_verification_promotes_or_demotes() -> None:
    tier1_story = _story(
        title="Company raises $5B",
        url="https://openai.com/news",
        source_tier=SourceTier.TIER_1,
        confidence=Confidence.MEDIUM,
    )
    unverified_story = _story(
        title="Startup raises $700M",
        url="https://unknown.example/funding",
        source_tier=SourceTier.TIER_3,
        confidence=Confidence.MEDIUM,
    )

    verified = enforce_numeric_claim_verification([tier1_story, unverified_story])

    assert verified[0].confidence == Confidence.HIGH
    assert verified[0].metadata["numeric_claims_verified"] is True
    assert verified[1].confidence == Confidence.LOW
    assert verified[1].metadata["numeric_claims_verified"] is False


def test_enforce_recency_handles_missing_and_stale_dates() -> None:
    now = datetime.now(UTC)
    in_window = _story(title="In", url="https://a.com", published_at=now - timedelta(days=1))
    stale = _story(title="Old", url="https://b.com", published_at=now - timedelta(days=20))
    missing = _story(title="Missing", url="https://c.com", published_at=None)

    filtered = enforce_recency(
        [in_window, stale, missing],
        start_at=now - timedelta(days=7),
        end_at=now,
    )

    assert len(filtered) == 2
    assert any(story.title == "In" for story in filtered)
    missing_story = next(story for story in filtered if story.title == "Missing")
    assert missing_story.confidence == Confidence.LOW
    assert missing_story.metadata["missing_timestamp"] is True


def test_citation_validation_and_planning_payload() -> None:
    story = _story(
        title="Story",
        url="https://example.com/1",
        source_name="Example",
        published_at=datetime(2026, 2, 27, tzinfo=UTC),
        confidence=Confidence.HIGH,
        source_tier=SourceTier.TIER_1,
    )

    errors = validate_citation_fields([story])
    payload = to_planning_inputs([story])

    assert errors == []
    assert payload[0]["confidence"] == "high"
    assert payload[0]["source_tier"] == 1


def test_canonicalize_resolves_google_news_url() -> None:
    """Google News RSS article URLs are resolved via HTTP HEAD."""
    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.url = "https://techcrunch.com/actual-article"

    with patch("services.quality.requests.head", return_value=mock_response):
        result = canonicalize_url(
            "https://news.google.com/rss/articles/CBMiZmh0dHBz"
        )

    assert "techcrunch.com/actual-article" in result


def test_canonicalize_google_news_url_fallback_on_failure() -> None:
    """Google News URL resolution falls back to original on network error."""
    from unittest.mock import patch

    with patch("services.quality.requests.head", side_effect=Exception("timeout")):
        result = canonicalize_url(
            "https://news.google.com/rss/articles/CBMiZmh0dHBz"
        )

    assert "news.google.com" in result
