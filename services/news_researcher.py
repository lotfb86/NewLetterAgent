"""Perplexity query execution and citation extraction service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from models import Confidence, SourceTier, StoryCandidate
from services.llm import OpenRouterClient

DEFAULT_RESEARCH_QUERIES: tuple[str, ...] = (
    "What are the biggest AI agent and digital labor announcements this week?",
    "What major AI startup funding rounds were announced this week?",
    "What new enterprise AI adoption news happened this week?",
    "What are the most hyped AI product launches or model releases this week?",
    "What AI industry trends or research breakthroughs are people talking about this week?",
)


@dataclass(frozen=True)
class QueryResearchResult:
    """Per-query research result from LLM and citations."""

    query: str
    content: str
    citations: tuple[str, ...]


class NewsResearcher:
    """Run Perplexity research queries and normalize citation stories."""

    def __init__(
        self,
        llm_client: OpenRouterClient,
        *,
        queries: tuple[str, ...] = DEFAULT_RESEARCH_QUERIES,
    ) -> None:
        self._llm_client = llm_client
        self._queries = queries

    def run_weekly_research(self) -> list[QueryResearchResult]:
        """Run configured queries and return normalized query-level results."""
        results: list[QueryResearchResult] = []
        for query in self._queries:
            try:
                response = self._llm_client.ask_perplexity(user_prompt=query)
                results.append(
                    QueryResearchResult(
                        query=query,
                        content=response.content,
                        citations=response.citations,
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return results

    def to_story_candidates(self, results: list[QueryResearchResult]) -> list[StoryCandidate]:
        """Convert query results and citations into normalized candidate stories."""
        now = datetime.now(UTC)
        stories: list[StoryCandidate] = []
        for result in results:
            titles_by_url = _extract_markdown_link_titles(result.content)
            for citation in result.citations:
                url = citation.strip()
                if not url:
                    continue
                title = titles_by_url.get(url) or _fallback_title(url)
                source_name = _source_name_from_url(url)
                stories.append(
                    StoryCandidate(
                        title=title,
                        source_url=url,
                        source_name=source_name,
                        published_at=now,
                        confidence=Confidence.MEDIUM,
                        source_tier=SourceTier.TIER_2,
                        summary=f"Derived from Perplexity query: {result.query}",
                        metadata={"query": result.query},
                    )
                )
        return _dedupe(stories)


def _extract_markdown_link_titles(content: str) -> dict[str, str]:
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    matches = pattern.findall(content)
    return {url.strip(): title.strip() for title, url in matches}


def _source_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "external-source"


def _fallback_title(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return _source_name_from_url(url)
    last = path.split("/")[-1].replace("-", " ").replace("_", " ").strip()
    return last.title() if last else _source_name_from_url(url)


def _dedupe(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    seen: set[str] = set()
    deduped: list[StoryCandidate] = []
    for story in stories:
        url = story.source_url.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        deduped.append(story)
    return deduped
