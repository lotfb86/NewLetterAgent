"""Tests for OpenRouter LLM client wrappers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.llm import OpenRouterClient


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


class _FakeResponse:
    def __init__(self, content: str, citations: list[str]) -> None:
        self.choices = [_FakeChoice(message=_FakeMessage(content=content))]
        self._citations = citations

    def model_dump(self) -> dict[str, Any]:
        return {
            "citations": self._citations,
            "choices": [{"message": {"content": self.choices[0].message.content}}],
        }


class _FakeCompletions:
    def create(self, **_: Any) -> _FakeResponse:
        return _FakeResponse("result text", ["https://example.com/a"])


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


def test_openrouter_client_normalizes_content_and_citations(app_config: Any) -> None:
    client = OpenRouterClient(app_config)
    client._client = _FakeOpenAIClient()  # type: ignore[assignment]

    result = client.ask_perplexity(user_prompt="what happened")

    assert result.content == "result text"
    assert result.citations == ("https://example.com/a",)
