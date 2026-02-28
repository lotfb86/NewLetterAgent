"""Tests for core typed models."""

from __future__ import annotations

from datetime import UTC, datetime

from models import Confidence, DraftStatus, RunStage, SourceTier, StoryCandidate


def test_story_candidate_fields() -> None:
    story = StoryCandidate(
        title="Title",
        source_url="https://example.com/story",
        source_name="Example",
        published_at=datetime(2026, 2, 27, 12, 0, tzinfo=UTC),
        confidence=Confidence.HIGH,
        source_tier=SourceTier.TIER_1,
    )

    assert story.confidence == Confidence.HIGH
    assert story.source_tier == SourceTier.TIER_1


def test_enums_have_expected_values() -> None:
    assert DraftStatus.PENDING_REVIEW.value == "pending_review"
    assert RunStage.RENDER_VALIDATED.value == "render_validated"
