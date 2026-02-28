"""Tests for deterministic newsletter renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.renderer import NewsletterRenderer
from services.validator import ContentValidationError


def _payload() -> dict[str, object]:
    return {
        "newsletter_name": "AI Weekly",
        "issue_date": "2026-02-27",
        "subject_line": "Subject",
        "preheader": "Preheader",
        "intro": "Intro",
        "team_updates": [{"title": "Update", "summary": "Summary"}],
        "industry_stories": [
            {
                "headline": "Story",
                "hook": "Hook",
                "why_it_matters": "Why",
                "source_url": "https://example.com/story",
                "source_name": "Example",
                "published_at": "2026-02-27T00:00:00Z",
                "confidence": "high",
            }
        ],
        "cta": {"text": "Contact us", "url": "https://example.com/contact"},
    }


def test_renderer_renders_template_successfully() -> None:
    renderer = NewsletterRenderer(
        template_path=Path("/Users/jesseanglen/NewLetterAgent/templates/newsletter_base.html")
    )

    html = renderer.render(_payload())

    assert "AI Weekly" in html
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html


def test_renderer_rejects_invalid_links() -> None:
    renderer = NewsletterRenderer(
        template_path=Path("/Users/jesseanglen/NewLetterAgent/templates/newsletter_base.html")
    )
    payload = _payload()
    payload["cta"] = {"text": "Contact", "url": "http://insecure.example.com"}

    with pytest.raises(ContentValidationError):
        renderer.render(payload)
