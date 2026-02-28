"""Tests for newsletter writer service."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from services.composition import CompositionFailure
from services.writer import NewsletterWriter


class _FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls = 0

    def ask_claude(self, **_: Any) -> Any:
        output = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return type("Resp", (), {"content": output})()


def test_writer_validates_and_repairs(app_config: Any) -> None:
    invalid = '{"newsletter_name": "X"}'
    valid = """
    {
      "newsletter_name": "AI Weekly",
      "issue_date": "2026-02-27",
      "subject_line": "This Week in AI",
      "preheader": "Top AI stories",
      "intro": "Intro text",
      "team_updates": [{"title": "Update", "summary": "Summary"}],
      "industry_stories": [{
        "headline": "Headline",
        "hook": "Hook",
        "why_it_matters": "Why",
        "source_url": "https://example.com/story",
        "source_name": "Example",
        "published_at": "2026-02-27T00:00:00Z",
        "confidence": "high"
      }],
      "cta": {"text": "Contact", "url": "https://example.com/contact"}
    }
    """

    writer = NewsletterWriter(app_config, _FakeLLM([invalid, valid]))  # type: ignore[arg-type]
    payload = writer.write_newsletter(
        newsletter_plan={
            "team_section": {"include": False, "items": []},
            "industry_section": {"items": []},
            "cta": {"text": "x"},
        },
        issue_date="2026-02-27",
        newsletter_name="AI Weekly",
    )

    assert payload["newsletter_name"] == "AI Weekly"


def test_writer_failure_writes_dead_letter(app_config: Any) -> None:
    config = replace(app_config, max_external_retries=2)
    writer = NewsletterWriter(config, _FakeLLM(["invalid", "invalid"]))  # type: ignore[arg-type]

    with pytest.raises(CompositionFailure) as exc_info:
        writer.write_newsletter(
            newsletter_plan={},
            issue_date="2026-02-27",
            newsletter_name="AI Weekly",
        )

    assert exc_info.value.dead_letter_path.exists()
    assert '"stage": "writer"' in exc_info.value.dead_letter_path.read_text(encoding="utf-8")


def test_writer_revise_newsletter_returns_valid_json(app_config: Any) -> None:
    revised = """
    {
      "newsletter_name": "AI Weekly",
      "issue_date": "2026-02-27",
      "subject_line": "This Week in AI",
      "preheader": "Top AI stories",
      "intro": "Updated intro",
      "team_updates": [{"title": "Update", "summary": "Summary"}],
      "industry_stories": [{
        "headline": "Headline",
        "hook": "Hook",
        "why_it_matters": "Why",
        "source_url": "https://example.com/story",
        "source_name": "Example",
        "published_at": "2026-02-27T00:00:00Z",
        "confidence": "high"
      }],
      "cta": {"text": "Contact", "url": "https://example.com/contact"}
    }
    """
    writer = NewsletterWriter(app_config, _FakeLLM([revised]))  # type: ignore[arg-type]

    payload = writer.revise_newsletter(
        current_draft={
            "newsletter_name": "AI Weekly",
            "issue_date": "2026-02-27",
            "subject_line": "Old",
            "preheader": "Old",
            "intro": "Old intro",
            "team_updates": [],
            "industry_stories": [],
            "cta": {"text": "Contact", "url": "https://example.com/contact"},
        },
        feedback_text="refresh intro",
    )

    assert payload["intro"] == "Updated intro"
