"""OpenRouter-backed LLM service wrappers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI

from config import AppConfig
from services.resilience import ResiliencePolicy

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CLAUDE_MODEL = "anthropic/claude-sonnet-4.6"
DEFAULT_PERPLEXITY_MODEL = "perplexity/sonar"
DEFAULT_GROK_MODEL = "x-ai/grok-3"


@dataclass(frozen=True)
class LLMResult:
    """Normalized LLM response payload."""

    model: str
    content: str
    citations: tuple[str, ...]
    raw_response: dict[str, Any]


class OpenRouterClient:
    """OpenRouter client with retry and timeout policy."""

    def __init__(self, config: AppConfig, *, timeout_seconds: float = 45.0) -> None:
        self._config = config
        self._client = OpenAI(
            api_key=config.openrouter_api_key,
            base_url=OPENROUTER_BASE_URL,
            timeout=timeout_seconds,
        )
        self._resilience = ResiliencePolicy(
            name="openrouter_chat",
            max_attempts=config.max_external_retries,
        )

    def chat(
        self,
        *,
        model: str,
        system_prompt: str | None,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> LLMResult:
        """Execute a chat completion request and normalize output."""

        def _operation() -> Any:
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            messages_payload = cast(Any, messages)

            return self._client.chat.completions.create(
                model=model,
                messages=messages_payload,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        response = self._resilience.execute(_operation)
        result = _normalize_response(model=model, response=response)
        if not result.content:
            logger.warning(
                "LLM returned empty content for model=%s (raw keys: %s)",
                model,
                list(result.raw_response.keys()) if result.raw_response else "none",
            )
        return result

    def ask_claude(
        self,
        *,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> LLMResult:
        """Convenience wrapper for Claude model requests."""
        return self.chat(
            model=DEFAULT_CLAUDE_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def ask_perplexity(
        self,
        *,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> LLMResult:
        """Convenience wrapper for Perplexity Sonar requests."""
        return self.chat(
            model=DEFAULT_PERPLEXITY_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def ask_grok(
        self,
        *,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> LLMResult:
        """Convenience wrapper for Grok (xAI) model requests."""
        return self.chat(
            model=DEFAULT_GROK_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def _normalize_response(*, model: str, response: Any) -> LLMResult:
    raw_dict = (
        response.model_dump() if hasattr(response, "model_dump") else _coerce_to_dict(response)
    )
    content = _extract_content(response)
    citations = _extract_citations(raw_dict)
    return LLMResult(
        model=model,
        content=content,
        citations=tuple(citations),
        raw_response=raw_dict,
    )


def _extract_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def _extract_citations(raw: dict[str, Any]) -> list[str]:
    candidates = raw.get("citations")
    if isinstance(candidates, list):
        return [str(item) for item in candidates if isinstance(item, (str, bytes))]

    data = raw.get("data")
    if isinstance(data, dict) and isinstance(data.get("citations"), list):
        return [str(item) for item in data["citations"] if isinstance(item, (str, bytes))]

    return []


def _coerce_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}

    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {"raw": str(value)}
