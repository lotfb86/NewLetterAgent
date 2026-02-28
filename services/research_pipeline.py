"""Weekly research orchestration, deduplication, and ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from config import AppConfig
from models import StoryCandidate, TeamUpdate
from services.brain import PublishedStory
from services.hacker_news import HackerNewsReader
from services.news_researcher import NewsResearcher, QueryResearchResult
from services.quality import (
    apply_canonicalization_and_tiering,
    enforce_numeric_claim_verification,
    enforce_recency,
    extract_numeric_claims,
    to_planning_inputs,
)
from services.rss_reader import RSSReader
from services.slack_reader import SlackReader

if TYPE_CHECKING:
    from services.grok_researcher import GrokResearcher


@dataclass(frozen=True)
class RankedStory:
    """Story with computed relevance score and ranking reasons."""

    story: StoryCandidate
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyResearchBundle:
    """Aggregated weekly research payload."""

    start_at: datetime
    end_at: datetime
    team_updates: tuple[TeamUpdate, ...]
    source_stories: tuple[StoryCandidate, ...]
    perplexity_results: tuple[QueryResearchResult, ...]
    candidate_stories: tuple[StoryCandidate, ...]
    ranked_stories: tuple[RankedStory, ...]
    planning_inputs: tuple[dict[str, str | int | None], ...]


class ResearchPipeline:
    """Orchestrate weekly source collection and story ranking."""

    def __init__(
        self,
        *,
        config: AppConfig,
        slack_reader: SlackReader,
        rss_reader: RSSReader,
        hacker_news_reader: HackerNewsReader,
        news_researcher: NewsResearcher,
        grok_researcher: GrokResearcher | None = None,
    ) -> None:
        self._config = config
        self._slack_reader = slack_reader
        self._rss_reader = rss_reader
        self._hacker_news_reader = hacker_news_reader
        self._news_researcher = news_researcher
        self._grok_researcher = grok_researcher

    def collect_sources(
        self, *, start_at: datetime, end_at: datetime
    ) -> tuple[list[TeamUpdate], list[StoryCandidate]]:
        """Collect Slack updates and non-LLM news sources for issue window."""
        updates = self._slack_reader.collect_weekly_updates(
            channel_id=self._config.newsletter_channel_id,
            start_at=start_at,
            end_at=end_at,
        )
        rss_stories = self._rss_reader.collect_recent_stories(
            lookback_days=max(1, (end_at - start_at).days + 1),
            now=end_at,
        )
        hn_stories = self._hacker_news_reader.fetch_top_stories(max_items=30)
        hn_recent = [
            story
            for story in hn_stories
            if story.published_at is None
            or (story.published_at >= start_at and story.published_at <= end_at)
        ]

        combined = merge_primary_dedupe([*rss_stories, *hn_recent])
        return updates, combined

    def run_weekly(
        self, *, start_at: datetime, end_at: datetime, published_stories: list[PublishedStory]
    ) -> WeeklyResearchBundle:
        """Run full research aggregation and ranking pipeline."""
        updates, source_stories = self.collect_sources(start_at=start_at, end_at=end_at)

        perplexity_results = self._news_researcher.run_weekly_research()
        perplexity_stories = self._news_researcher.to_story_candidates(perplexity_results)

        grok_stories: list[StoryCandidate] = []
        if self._grok_researcher is not None and self._grok_researcher.enabled:
            grok_results = self._grok_researcher.run_research()
            grok_stories = self._grok_researcher.to_story_candidates(grok_results)

        merged = merge_primary_dedupe([*source_stories, *perplexity_stories, *grok_stories])
        canonicalized = apply_canonicalization_and_tiering(merged)
        secondary = secondary_dedupe(canonicalized)
        verified = enforce_numeric_claim_verification(secondary)
        recent = enforce_recency(verified, start_at=start_at, end_at=end_at)
        unpublished = filter_previously_published(
            candidates=recent,
            published=published_stories,
            lookback_weeks=self._config.dedup_lookback_weeks,
            now=end_at,
        )
        ranked = rank_stories_by_relevance(unpublished)
        planning_inputs = to_planning_inputs([r.story for r in ranked])

        return WeeklyResearchBundle(
            start_at=start_at,
            end_at=end_at,
            team_updates=tuple(updates),
            source_stories=tuple(source_stories),
            perplexity_results=tuple(perplexity_results),
            candidate_stories=tuple(unpublished),
            ranked_stories=tuple(ranked),
            planning_inputs=tuple(planning_inputs),
        )


def merge_primary_dedupe(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    """Dedupe candidates by canonical URL and exact normalized title."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[StoryCandidate] = []

    for story in stories:
        normalized_url = _normalize_url(story.source_url)
        normalized_title = _normalize_title(story.title)

        if normalized_url in seen_urls:
            continue
        if normalized_title in seen_titles:
            continue

        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        deduped.append(story)

    return deduped


def secondary_dedupe(
    stories: list[StoryCandidate], *, similarity_threshold: float = 0.86
) -> list[StoryCandidate]:
    """Dedupe near-duplicates and obvious follow-up rehash stories."""
    deduped: list[StoryCandidate] = []
    for candidate in stories:
        if any(
            _is_probable_duplicate(candidate, existing, similarity_threshold)
            for existing in deduped
        ):
            continue
        deduped.append(candidate)
    return deduped


def filter_previously_published(
    *,
    candidates: list[StoryCandidate],
    published: list[PublishedStory],
    lookback_weeks: int,
    now: datetime,
) -> list[StoryCandidate]:
    """Remove candidates matching stories already published in lookback window."""
    cutoff_date = (now - timedelta(weeks=lookback_weeks)).date()

    relevant_published = [
        entry for entry in published if _parse_issue_date(entry.issue_date) >= cutoff_date
    ]
    published_urls = {_normalize_url(entry.url) for entry in relevant_published}
    published_titles = {_normalize_title(entry.title) for entry in relevant_published}

    filtered: list[StoryCandidate] = []
    for candidate in candidates:
        normalized_url = _normalize_url(candidate.source_url)
        normalized_title = _normalize_title(candidate.title)

        if normalized_url in published_urls:
            continue
        if normalized_title in published_titles:
            continue

        # Fuzzy title match against published history for cross-outlet dedup.
        is_fuzzy_dup = False
        for pub in relevant_published:
            pub_title = _normalize_title(pub.title)
            if SequenceMatcher(None, normalized_title, pub_title).ratio() >= 0.82:
                is_fuzzy_dup = True
                break
        if is_fuzzy_dup:
            continue

        filtered.append(candidate)

    return filtered


def rank_stories_by_relevance(stories: list[StoryCandidate]) -> list[RankedStory]:
    """Compute relevance score and return stories sorted highest-first."""
    ranked = [
        RankedStory(story=story, score=score, reasons=tuple(reasons))
        for story in stories
        for score, reasons in [_compute_relevance(story)]
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def _compute_relevance(story: StoryCandidate) -> tuple[float, list[str]]:
    text = f"{story.title} {story.summary or ''}".lower()
    score = 0.0
    reasons: list[str] = []

    keyword_weights: tuple[tuple[str, float, str], ...] = (
        ("human emulator", 2.5, "human_emulators"),
        ("digital employee", 2.5, "digital_employees"),
        ("ai employee", 2.5, "ai_employees"),
        ("agent", 2.0, "ai_agents"),
        ("digital labor", 2.0, "digital_labor"),
        ("funding", 1.8, "funding"),
        ("raised", 1.2, "funding_signal"),
        ("enterprise", 1.5, "enterprise"),
        ("automation", 1.3, "automation"),
        ("model", 1.0, "model_release"),
    )

    for keyword, weight, reason in keyword_weights:
        if keyword in text:
            score += weight
            reasons.append(reason)

    if story.source_tier.value == 1:
        score += 1.0
        reasons.append("tier1_source")
    elif story.source_tier.value == 2:
        score += 0.5
        reasons.append("tier2_source")

    score += {
        "high": 1.0,
        "medium": 0.4,
        "low": 0.0,
    }[story.confidence.value]

    return score, reasons


def _normalize_url(url: str) -> str:
    stripped = url.strip().rstrip("/")
    parsed = urlparse(stripped)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{parsed.path}".lower()


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _parse_issue_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC).date()


# Multi-word entities: "Microsoft Azure", "Google Cloud", "Open AI"
_MULTI_WORD_ENTITY = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
# Mixed-case proper nouns: OpenAI, DeepMind, iPhone, etc.
_MIXED_CASE_NOUN = re.compile(r"\b[A-Z][a-zA-Z]*[A-Z][a-zA-Z]*\b")
_ENTITY_STOP = frozenset({"the", "this", "that", "with", "from", "new", "how", "who"})


def _extract_key_entities(text: str) -> set[str]:
    """Extract proper nouns and multi-word entity names from text."""
    entities: set[str] = set()
    for m in _MULTI_WORD_ENTITY.finditer(text):
        entities.add(m.group(0).lower())
    for m in _MIXED_CASE_NOUN.finditer(text):
        word = m.group(0)
        if len(word) >= 3 and word.lower() not in _ENTITY_STOP:
            entities.add(word.lower())
    return entities


def _is_probable_duplicate(
    candidate: StoryCandidate, existing: StoryCandidate, threshold: float
) -> bool:
    if _normalize_url(candidate.source_url) == _normalize_url(existing.source_url):
        return True

    cand_title = _normalize_title(candidate.title)
    exist_title = _normalize_title(existing.title)

    similarity = SequenceMatcher(None, cand_title, exist_title).ratio()
    if similarity >= threshold:
        return True

    # Cross-outlet dedup: compare title+summary combined text.
    cand_summary = (candidate.summary or "").lower().strip()
    exist_summary = (existing.summary or "").lower().strip()
    if cand_summary and exist_summary:
        cand_combined = f"{cand_title} {cand_summary}"
        exist_combined = f"{exist_title} {exist_summary}"
        if SequenceMatcher(None, cand_combined, exist_combined).ratio() >= 0.55:
            return True

    # Entity-based matching: shared company/product names + moderate title overlap.
    cand_text = f"{candidate.title} {candidate.summary or ''}"
    exist_text = f"{existing.title} {existing.summary or ''}"
    shared_entities = _extract_key_entities(cand_text) & _extract_key_entities(exist_text)
    if len(shared_entities) >= 1 and similarity >= 0.55:
        return True

    # Numeric claim + entity dedup: same dollar amount AND shared entity
    # strongly implies same event from different outlets.
    cand_claims = set(extract_numeric_claims(cand_text))
    exist_claims = set(extract_numeric_claims(exist_text))
    if (cand_claims & exist_claims) and shared_entities:
        return True

    # Follow-up heuristic: same source and high token overlap.
    if candidate.source_name == existing.source_name:
        candidate_tokens = set(cand_title.split())
        existing_tokens = set(exist_title.split())
        if candidate_tokens and existing_tokens:
            overlap = len(candidate_tokens & existing_tokens) / len(
                candidate_tokens | existing_tokens
            )
            if overlap >= 0.8:
                return True

    return False
