"""Tests for weekly research orchestration and dedupe/ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from models import Confidence, SourceTier, StoryCandidate, TeamUpdate
from services.brain import PublishedStory
from services.news_researcher import QueryResearchResult
from services.research_pipeline import (
    ResearchPipeline,
    filter_previously_published,
    merge_primary_dedupe,
    rank_stories_by_relevance,
    secondary_dedupe,
)


@dataclass
class _FakeSlackReader:
    updates: list[TeamUpdate]

    def collect_weekly_updates(self, **_: Any) -> list[TeamUpdate]:
        return self.updates


@dataclass
class _FakeRssReader:
    stories: list[StoryCandidate]

    def collect_recent_stories(self, **_: Any) -> list[StoryCandidate]:
        return self.stories


@dataclass
class _FakeHnReader:
    stories: list[StoryCandidate]

    def fetch_top_stories(self, **_: Any) -> list[StoryCandidate]:
        return self.stories


@dataclass
class _FakeNewsResearcher:
    results: list[QueryResearchResult]
    stories: list[StoryCandidate]

    def run_weekly_research(self) -> list[QueryResearchResult]:
        return self.results

    def to_story_candidates(self, _: list[QueryResearchResult]) -> list[StoryCandidate]:
        return self.stories


def _story(
    title: str,
    url: str,
    *,
    source: str = "example",
    confidence: Confidence = Confidence.MEDIUM,
    tier: SourceTier = SourceTier.TIER_2,
) -> StoryCandidate:
    return StoryCandidate(
        title=title,
        source_url=url,
        source_name=source,
        published_at=datetime.now(UTC),
        confidence=confidence,
        source_tier=tier,
        summary="",
    )


def test_merge_primary_dedupe_uses_url_and_title() -> None:
    stories = [
        _story("AI Agent Launch", "https://example.com/a"),
        _story("AI Agent Launch", "https://other.com/other"),
        _story("Different", "https://example.com/a/"),
    ]

    deduped = merge_primary_dedupe(stories)

    assert len(deduped) == 1


def test_secondary_dedupe_filters_near_duplicates() -> None:
    stories = [
        _story("OpenAI launches enterprise agent platform", "https://a.com/1"),
        _story("OpenAI launches enterprise agents platform", "https://b.com/2"),
    ]

    deduped = secondary_dedupe(stories)

    assert len(deduped) == 1


def test_filter_previously_published_respects_lookback() -> None:
    now = datetime(2026, 3, 1, tzinfo=UTC)
    candidates = [
        _story("Already Sent", "https://example.com/already"),
        _story("New Story", "https://example.com/new"),
    ]
    published = [
        PublishedStory(
            issue_date="2026-02-27",
            title="Already Sent",
            url="https://example.com/already",
        )
    ]

    filtered = filter_previously_published(
        candidates=candidates,
        published=published,
        lookback_weeks=12,
        now=now,
    )

    assert len(filtered) == 1
    assert filtered[0].title == "New Story"


def test_rank_stories_by_relevance_orders_highest_first() -> None:
    low = _story("General model update", "https://a.com", confidence=Confidence.LOW)
    high = _story(
        "Enterprise AI agent funding round",
        "https://b.com",
        confidence=Confidence.HIGH,
        tier=SourceTier.TIER_1,
    )

    ranked = rank_stories_by_relevance([low, high])

    assert ranked[0].story.title == high.title
    assert ranked[0].score > ranked[1].score


def test_secondary_dedupe_catches_same_event_different_outlets() -> None:
    """Stories about the same event from different outlets should be deduped via summary."""
    from dataclasses import replace

    stories = [
        _story(
            "OpenAI Raises $6.5B in Latest Funding Round",
            "https://techcrunch.com/openai-funding",
            source="techcrunch.com",
        ),
        _story(
            "OpenAI Secures $6.5 Billion in New Funding",
            "https://bloomberg.com/openai-funding",
            source="bloomberg.com",
        ),
    ]
    stories[0] = replace(stories[0], summary="OpenAI has raised $6.5B in its latest round")
    stories[1] = replace(stories[1], summary="OpenAI secured $6.5 billion in new funding round")

    deduped = secondary_dedupe(stories)

    assert len(deduped) == 1


def test_filter_previously_published_fuzzy_title_match() -> None:
    """Near-duplicate titles in brain should still be filtered."""
    now = datetime(2026, 3, 1, tzinfo=UTC)
    candidates = [
        _story("Google Launches Gemini 2.0 AI Model", "https://new-outlet.com/gemini"),
    ]
    published = [
        PublishedStory(
            issue_date="2026-02-27",
            title="Google launches Gemini 2.0 AI model",
            url="https://old-outlet.com/google-gemini",
        ),
    ]

    filtered = filter_previously_published(
        candidates=candidates,
        published=published,
        lookback_weeks=12,
        now=now,
    )

    assert len(filtered) == 0


def test_secondary_dedupe_entity_based_matching() -> None:
    """Stories sharing key entities with moderate title overlap are deduped."""
    from dataclasses import replace

    stories = [
        _story(
            "Microsoft Azure expands AI services for enterprises",
            "https://a.com/ms-azure",
        ),
        _story(
            "Microsoft Azure launches new AI features for business",
            "https://b.com/ms-azure-ai",
        ),
    ]
    stories[0] = replace(stories[0], summary="Microsoft Azure rollout of new AI services")
    stories[1] = replace(stories[1], summary="Microsoft Azure adds AI features for business")

    deduped = secondary_dedupe(stories)

    assert len(deduped) == 1


def test_research_pipeline_collects_and_ranks(app_config: Any) -> None:
    now = datetime.now(UTC)
    slack_reader = _FakeSlackReader(
        updates=[
            TeamUpdate(message_ts="1", user_id="U1", text="Team shipped feature"),
        ]
    )
    rss_reader = _FakeRssReader(stories=[_story("RSS Story", "https://rss.com/a")])
    hn_reader = _FakeHnReader(
        stories=[_story("HN Story", "https://hn.com/a", source="Hacker News")]
    )
    news_researcher = _FakeNewsResearcher(
        results=[QueryResearchResult(query="Q1", content="content", citations=("https://q.com",))],
        stories=[_story("Perplexity Story", "https://q.com")],
    )

    pipeline = ResearchPipeline(
        config=app_config,
        slack_reader=slack_reader,  # type: ignore[arg-type]
        rss_reader=rss_reader,  # type: ignore[arg-type]
        hacker_news_reader=hn_reader,  # type: ignore[arg-type]
        news_researcher=news_researcher,  # type: ignore[arg-type]
    )

    bundle = pipeline.run_weekly(
        start_at=now - timedelta(days=7),
        end_at=now + timedelta(minutes=5),
        published_stories=[],
    )

    assert len(bundle.team_updates) == 1
    assert len(bundle.source_stories) >= 1
    assert len(bundle.perplexity_results) == 1
    assert len(bundle.ranked_stories) >= 1
