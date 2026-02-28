"""Tests for services.grok_researcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.grok_researcher import GrokResearcher


@dataclass
class _FakeResult:
    content: str
    citations: tuple[str, ...] = ()


class _FakeLLM:
    def __init__(self, content: str = "") -> None:
        self._content = content
        self.calls: list[str] = []

    def ask_grok(self, *, user_prompt: str, **_: Any) -> _FakeResult:
        self.calls.append(user_prompt)
        return _FakeResult(content=self._content)


def test_grok_researcher_produces_story_candidates() -> None:
    fake = _FakeLLM(
        content=(
            "Here are trending AI topics:\n"
            "- [OpenAI launches GPT-5](https://example.com/gpt5)\n"
            "- [Anthropic raises $2B](https://example.com/anthropic)\n"
        )
    )
    researcher = GrokResearcher(
        fake,  # type: ignore[arg-type]
        queries=("Test query",),
        enabled=True,
    )

    results = researcher.run_research()
    stories = researcher.to_story_candidates(results)

    assert len(results) == 1
    assert len(stories) == 2
    assert stories[0].source_url == "https://example.com/gpt5"
    assert stories[0].title == "OpenAI launches GPT-5"
    assert stories[0].metadata.get("source_type") == "grok"
    assert stories[1].source_url == "https://example.com/anthropic"


def test_grok_researcher_disabled_returns_empty() -> None:
    researcher = GrokResearcher(
        _FakeLLM(),  # type: ignore[arg-type]
        queries=("Test query",),
        enabled=False,
    )

    results = researcher.run_research()
    assert results == []


def test_grok_researcher_dedupes_by_url() -> None:
    fake = _FakeLLM(
        content=(
            "[Story A](https://example.com/same) and also [Story B](https://example.com/same)"
        )
    )
    researcher = GrokResearcher(
        fake,  # type: ignore[arg-type]
        queries=("Q",),
        enabled=True,
    )

    results = researcher.run_research()
    stories = researcher.to_story_candidates(results)

    assert len(stories) == 1


def test_grok_researcher_handles_llm_failure_gracefully() -> None:
    class _FailLLM:
        def ask_grok(self, **_: Any) -> None:
            raise RuntimeError("Model unavailable")

    researcher = GrokResearcher(
        _FailLLM(),  # type: ignore[arg-type]
        queries=("Q",),
        enabled=True,
    )

    results = researcher.run_research()
    assert results == []


def test_grok_researcher_multiple_queries() -> None:
    fake = _FakeLLM(content="[Story](https://example.com/s)")
    researcher = GrokResearcher(
        fake,  # type: ignore[arg-type]
        queries=("Q1", "Q2", "Q3"),
        enabled=True,
    )

    results = researcher.run_research()
    assert len(results) == 3
    assert len(fake.calls) == 3
