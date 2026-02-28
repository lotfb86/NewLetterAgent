"""Slack preview formatter from canonical newsletter JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_BLOCK_TEXT_CHARS = 3000
MAX_BLOCKS_PER_MESSAGE = 50


@dataclass(frozen=True)
class SlackPreviewResult:
    """Slack preview payload with support for multi-message overflow."""

    messages: tuple[tuple[dict[str, Any], ...], ...]
    full_draft_snippet: str


class SlackPreviewFormatter:
    """Format newsletter JSON for Slack Block Kit preview."""

    def format_preview(self, newsletter_payload: dict[str, Any]) -> SlackPreviewResult:
        """Build preview messages while respecting Slack block limits."""
        markdown_sections = _build_markdown_sections(newsletter_payload)
        full_draft = "\n\n".join(markdown_sections)

        blocks = _sections_to_blocks(markdown_sections)
        message_batches = _split_blocks(blocks, max_blocks=MAX_BLOCKS_PER_MESSAGE)

        # Mark continuation on overflow messages for operator clarity.
        if len(message_batches) > 1:
            for index in range(1, len(message_batches)):
                message_batches[index] = (
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*Draft preview continued ({index + 1}/{len(message_batches)})*"
                            ),
                        },
                    },
                    *message_batches[index],
                )

        return SlackPreviewResult(
            messages=tuple(tuple(batch) for batch in message_batches),
            full_draft_snippet=full_draft,
        )


def _build_markdown_sections(payload: dict[str, Any]) -> list[str]:
    sections: list[str] = []
    sections.append(
        f"*{payload.get('newsletter_name', 'Newsletter')}*\n"
        f"Issue date: {payload.get('issue_date', 'unknown')}"
    )
    sections.append(payload.get("intro", ""))

    team_updates = payload.get("team_updates", [])
    if isinstance(team_updates, list) and team_updates:
        team_lines = ["*What We've Been Up To*"]
        for item in team_updates:
            title = str(item.get("title", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if title:
                team_lines.append(f"• *{title}* — {summary}")
        sections.append("\n".join(team_lines))

    industry_stories = payload.get("industry_stories", [])
    if isinstance(industry_stories, list):
        story_lines = ["*This Week in AI*"]
        for story in industry_stories:
            headline = str(story.get("headline", "")).strip()
            hook = str(story.get("hook", "")).strip()
            why = str(story.get("why_it_matters", "")).strip()
            url = str(story.get("source_url", "")).strip()
            confidence = str(story.get("confidence", "")).strip()
            story_lines.append(
                f"• *<{url}|{headline}>*\n"
                f"  {hook}\n"
                f"  _Why it matters:_ {why} (confidence: {confidence})"
            )
        sections.append("\n".join(story_lines))

    cta = payload.get("cta", {})
    if isinstance(cta, dict):
        sections.append(f"*CTA*\n{cta.get('text', '')}\n<{cta.get('url', '')}|Contact us>")

    return [section for section in sections if section.strip()]


def _sections_to_blocks(sections: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in sections:
        for chunk in _split_text(section, MAX_BLOCK_TEXT_CHARS):
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": chunk,
                    },
                }
            )
    return blocks


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = text
    while len(current) > max_chars:
        split_at = current.rfind("\n", 0, max_chars)
        if split_at == -1:
            split_at = current.rfind(" ", 0, max_chars)
        if split_at == -1:
            split_at = max_chars

        chunk = current[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        current = current[split_at:].strip()

    if current:
        chunks.append(current)

    return chunks


def _split_blocks(
    blocks: list[dict[str, Any]],
    *,
    max_blocks: int,
) -> list[tuple[dict[str, Any], ...]]:
    if not blocks:
        return [tuple()]

    output: list[tuple[dict[str, Any], ...]] = []
    for start in range(0, len(blocks), max_blocks):
        output.append(tuple(blocks[start : start + max_blocks]))
    return output
