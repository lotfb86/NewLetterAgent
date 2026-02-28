"""Grok/xAI research for X/Twitter trending AI topics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from models import Confidence, SourceTier, StoryCandidate
from services.llm import OpenRouterClient
from services.research_utils import (
    dedupe_by_url,
    extract_markdown_link_titles,
    extract_urls,
    fallback_title,
    source_name_from_url,
)

DEFAULT_GROK_QUERIES: tuple[str, ...] = (
    (
        "What AI topics are trending on X/Twitter right now? "
        "For each, provide a one-sentence summary and a source URL as a markdown link."
    ),
    (
        "What are the most discussed AI product launches or announcements on X today? "
        "Include source URLs formatted as markdown links."
    ),
    (
        "What discussions about AI agents, digital employees, or human emulation "
        "are trending on X/Twitter? Focus on enterprise automation and AI workforce developments. "
        "Provide source URLs for each story."
    ),
)

GROK_SYSTEM_PROMPT = (
    "You are a research assistant focused on AI industry news trending on X/Twitter. "
    "For each topic, provide a brief summary and include source URLs. "
    "Format each story as a markdown link: [Title](URL). "
    "Focus on the most significant AI developments being discussed."
)


@dataclass(frozen=True)
class GrokResearchResult:
    """Per-query research result from Grok."""

    query: str
    content: str
    urls: tuple[str, ...]


class GrokResearcher:
    """Run Grok research queries for X/Twitter trending AI topics."""

    def __init__(
        self,
        llm_client: OpenRouterClient,
        *,
        queries: tuple[str, ...] = DEFAULT_GROK_QUERIES,
        enabled: bool = True,
    ) -> None:
        self._llm_client = llm_client
        self._queries = queries
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def run_research(self) -> list[GrokResearchResult]:
        """Run configured queries and return results."""
        if not self._enabled:
            return []

        results: list[GrokResearchResult] = []
        for query in self._queries:
            try:
                response = self._llm_client.ask_grok(
                    system_prompt=GROK_SYSTEM_PROMPT,
                    user_prompt=query,
                )
                urls = extract_urls(response.content)
                results.append(
                    GrokResearchResult(
                        query=query,
                        content=response.content,
                        urls=tuple(urls),
                    )
                )
            except Exception:  # noqa: BLE001
                # Gracefully skip if Grok model is unavailable on OpenRouter.
                continue
        return results

    def to_story_candidates(
        self, results: list[GrokResearchResult]
    ) -> list[StoryCandidate]:
        """Convert Grok results into normalized story candidates."""
        now = datetime.now(UTC)
        stories: list[StoryCandidate] = []
        for result in results:
            titles_by_url = extract_markdown_link_titles(result.content)
            for url in result.urls:
                url = url.strip()
                if not url:
                    continue
                title = titles_by_url.get(url) or fallback_title(url)
                source_name = source_name_from_url(url)
                stories.append(
                    StoryCandidate(
                        title=title,
                        source_url=url,
                        source_name=source_name,
                        published_at=now,
                        confidence=Confidence.LOW,
                        source_tier=SourceTier.TIER_3,
                        summary=f"Trending on X/Twitter via Grok: {result.query[:80]}",
                        metadata={"query": result.query, "source_type": "grok"},
                    )
                )
        return dedupe_by_url(stories)
