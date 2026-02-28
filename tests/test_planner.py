"""Tests for newsletter planner service."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from models import TeamUpdate
from services.composition import CompositionFailure
from services.planner import NewsletterPlanner


class _FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls = 0

    def ask_claude(self, **_: Any) -> Any:
        output = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return type("Resp", (), {"content": output})()


def test_planner_repairs_invalid_json(app_config: Any) -> None:
    llm = _FakeLLM(
        outputs=[
            "not json",
            """
            {
              "team_section": {"include": true, "items": [{"title": "Update", "summary": "Done"}]},
              "industry_section": {"items": [{
                "headline": "Story",
                "hook": "Hook",
                "why_it_matters": "Why",
                "source_url": "https://example.com",
                "source_name": "Example",
                "published_at": "2026-02-27T00:00:00Z",
                "confidence": "high"
              }]},
              "cta": {"text": "Reach out"}
            }
            """,
        ]
    )

    planner = NewsletterPlanner(app_config, llm)  # type: ignore[arg-type]
    plan = planner.create_plan(
        team_updates=[
            TeamUpdate(
                message_ts="1",
                user_id="U1",
                text="Shipped",
                thread_replies=(),
            )
        ],
        industry_story_inputs=[
            {
                "title": "Story",
                "source_url": "https://example.com",
                "source_name": "Example",
                "published_at": datetime.now(UTC).isoformat(),
                "confidence": "high",
                "source_tier": 1,
                "summary": "Summary",
            }
        ],
    )

    assert plan["cta"]["text"] == "Reach out"
    assert llm.calls == 2


def test_planner_failure_writes_dead_letter(app_config: Any) -> None:
    config = replace(app_config, max_external_retries=2)
    llm = _FakeLLM(outputs=["not json", "still not json"])
    planner = NewsletterPlanner(config, llm)  # type: ignore[arg-type]

    with pytest.raises(CompositionFailure) as exc_info:
        planner.create_plan(team_updates=[], industry_story_inputs=[])

    assert exc_info.value.dead_letter_path.exists()
    payload = exc_info.value.dead_letter_path.read_text(encoding="utf-8")
    assert '"stage": "planner"' in payload
