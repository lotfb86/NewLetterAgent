"""Tests for services.news_researcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.news_researcher import NewsResearcher


@dataclass
class _Result:
    content: str
    citations: tuple[str, ...]


class _FakeLLM:
    def ask_perplexity(self, *, user_prompt: str, **_: Any) -> _Result:
        return _Result(
            content=f"[{user_prompt}](https://example.com/story)",
            citations=("https://example.com/story",),
        )


def test_news_researcher_maps_results_to_story_candidates() -> None:
    researcher = NewsResearcher(_FakeLLM(), queries=("Query",))  # type: ignore[arg-type]

    query_results = researcher.run_weekly_research()
    stories = researcher.to_story_candidates(query_results)

    assert len(query_results) == 1
    assert len(stories) == 1
    assert stories[0].source_url == "https://example.com/story"
