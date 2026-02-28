"""Newsletter planning orchestration and schema handling."""

from __future__ import annotations

import json
import logging
from typing import Any

from config import AppConfig
from models import TeamUpdate
from services.composition import CompositionFailure, save_composition_dead_letter
from services.llm import OpenRouterClient
from services.schemas import PLANNER_SCHEMA
from services.validator import ContentValidationError, extract_json_payload, validate_json_payload

logger = logging.getLogger(__name__)

# Maximum number of stories to include in the planner prompt to avoid
# bloated payloads that degrade model output quality.
_MAX_PLANNER_STORIES = 12

# Truncate individual story summaries beyond this length (characters).
_MAX_SUMMARY_CHARS = 300

PLANNER_SYSTEM_PROMPT = (
    "You are the newsletter planning assistant for The Ruh Digest, "
    "the weekly AI industry newsletter published by Ruh.ai. "
    "Ruh.ai builds human emulators and AI digital employees for enterprise clients. "
    "Your audience includes enterprise decision-makers and investors interested in "
    "AI agents, digital labor, and enterprise automation. "
    "Output ONLY a single JSON object. "
    "Do NOT include markdown code fences, commentary, or any text "
    "before or after the JSON object."
)

PLANNER_STYLE_GUIDANCE = (
    "STYLE INTENT FOR DOWNSTREAM WRITING:\n"
    "- Prioritize angles that can be explained in human, relatable language.\n"
    "- Favor story framing with wit and personality over dry summary phrasing.\n"
    "- Allow occasional playful sarcasm about hype cycles, not about people.\n"
    "- Hooks should be entertaining and specific, never generic buzzword fluff.\n"
)


class NewsletterPlanner:
    """Generate newsletter outline JSON from team updates and story inputs."""

    def __init__(self, config: AppConfig, llm_client: OpenRouterClient) -> None:
        self._config = config
        self._llm_client = llm_client

    def create_plan(
        self,
        *,
        team_updates: list[TeamUpdate],
        industry_story_inputs: list[dict[str, str | int | None]],
    ) -> dict[str, Any]:
        """Generate and validate planner JSON with repair retries."""
        # Cap story count to keep the prompt within reasonable bounds.
        capped_stories = industry_story_inputs[:_MAX_PLANNER_STORIES]
        # Truncate long summaries to prevent payload bloat.
        trimmed_stories = [
            {**story, "summary": _truncate(story.get("summary"), _MAX_SUMMARY_CHARS)}
            for story in capped_stories
        ]
        if len(industry_story_inputs) > _MAX_PLANNER_STORIES:
            logger.info(
                "Capped planner stories from %d to %d",
                len(industry_story_inputs),
                _MAX_PLANNER_STORIES,
            )

        input_payload: dict[str, Any] = {
            "team_updates": [
                {
                    "text": item.text,
                    "thread_replies": list(item.thread_replies),
                }
                for item in team_updates
            ],
            "industry_stories": trimmed_stories,
        }

        initial_prompt = self._build_prompt(input_payload)
        prompt = initial_prompt
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for attempt_num in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=16384,
            )
            last_output = result.content
            logger.info(
                "Planner attempt %d/%d: model returned %d chars (first 200: %r)",
                attempt_num,
                attempts,
                len(result.content),
                result.content[:200],
            )
            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, PLANNER_SCHEMA)
                return payload
            except ContentValidationError as exc:
                last_error = str(exc)
                logger.warning(
                    "Planner attempt %d/%d failed: %s",
                    attempt_num,
                    attempts,
                    last_error,
                )
                prompt = self._build_repair_prompt(
                    original_prompt=initial_prompt,
                    invalid_output=result.content,
                    error_message=last_error,
                )

        dead_letter = save_composition_dead_letter(
            failure_dir=self._config.failure_log_dir,
            stage="planner",
            attempts=attempts,
            error_summary=last_error,
            input_payload=input_payload,
            last_model_output=last_output,
        )
        raise CompositionFailure(
            stage="planner",
            attempts=attempts,
            error_summary=last_error,
            dead_letter_path=dead_letter,
        )

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        return (
            "Plan this week's newsletter using the provided inputs.\n"
            "RULES:\n"
            "- Numeric claims require confidence high; otherwise avoid hard "
            "numbers or label as reportedly.\n"
            "- Only include stories in the current issue window unless "
            "explicitly marked unavoidable.\n"
            "- Include confidence for each industry item.\n"
            "- Make planned hooks and summaries support a very human, witty tone.\n"
            "- Prioritize stories most relevant to our audience: AI agents, digital labor, "
            "enterprise automation, human emulation, and AI employee developments.\n"
            "- Frame stories through the lens of business impact and investment opportunity.\n\n"
            f"{PLANNER_STYLE_GUIDANCE}\n"
            "Return a JSON object with this exact structure (no extra keys):\n"
            "{\n"
            '  "team_section": {\n'
            '    "include": true,\n'
            '    "items": [{"title": "...", "summary": "..."}]\n'
            "  },\n"
            '  "industry_section": {\n'
            '    "items": [{\n'
            '      "headline": "...",\n'
            '      "hook": "...",\n'
            '      "why_it_matters": "...",\n'
            '      "source_url": "https://...",\n'
            '      "source_name": "...",\n'
            '      "published_at": "2026-02-28",\n'
            '      "confidence": "high|medium|low"\n'
            "    }]\n"
            "  },\n"
            '  "cta": {"text": "..."}\n'
            "}\n\n"
            f"INPUT:\n{json.dumps(payload, indent=2, sort_keys=True)}\n\n"
            "IMPORTANT: Respond ONLY with the JSON object. "
            "Do not include any explanation, commentary, or markdown formatting. "
            "Start your response with { and end with }."
        )


    @staticmethod
    def _build_repair_prompt(
        *,
        original_prompt: str,
        invalid_output: str,
        error_message: str,
    ) -> str:
        return (
            "Your previous output was invalid. Repair and return only valid JSON.\n"
            f"Validation error: {error_message}\n\n"
            "Original task:\n"
            f"{original_prompt}\n\n"
            "Invalid output:\n"
            f"{invalid_output}"
        )


def _truncate(value: str | int | None, max_chars: int) -> str | int | None:
    """Truncate a string value to *max_chars*, appending '…' when clipped."""
    if not isinstance(value, str) or len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0] + "…"
