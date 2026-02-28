"""Tests for Slack preview formatter."""

from __future__ import annotations

from services.formatter import MAX_BLOCK_TEXT_CHARS, SlackPreviewFormatter


def _payload(long_text: str = "") -> dict[str, object]:
    return {
        "newsletter_name": "AI Weekly",
        "issue_date": "2026-02-27",
        "intro": long_text or "Intro",
        "team_updates": [{"title": "Update", "summary": "Summary"}],
        "industry_stories": [
            {
                "headline": "Story",
                "hook": "Hook",
                "why_it_matters": "Why",
                "source_url": "https://example.com/story",
                "source_name": "Example",
                "confidence": "high",
            }
        ],
        "cta": {"text": "Contact", "url": "https://example.com/contact"},
    }


def test_formatter_builds_preview_messages() -> None:
    formatter = SlackPreviewFormatter()

    result = formatter.format_preview(_payload())

    assert len(result.messages) >= 1
    assert "AI Weekly" in result.full_draft_snippet


def test_formatter_splits_large_blocks() -> None:
    formatter = SlackPreviewFormatter()
    large_intro = "A" * (MAX_BLOCK_TEXT_CHARS + 800)

    result = formatter.format_preview(_payload(long_text=large_intro))

    assert len(result.messages) >= 1
    first_message_blocks = result.messages[0]
    assert len(first_message_blocks) >= 2
