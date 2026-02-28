"""Newsletter planning orchestration and schema handling."""

from __future__ import annotations

import json
from typing import Any

from config import AppConfig
from models import TeamUpdate
from services.composition import CompositionFailure, save_composition_dead_letter
from services.llm import OpenRouterClient
from services.schemas import PLANNER_SCHEMA
from services.validator import ContentValidationError, extract_json_payload, validate_json_payload

PLANNER_SYSTEM_PROMPT = (
    "You are a newsletter planning assistant. Return valid JSON only. "
    "Do not include markdown fences or prose outside the JSON object."
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
        input_payload: dict[str, Any] = {
            "team_updates": [
                {
                    "text": item.text,
                    "thread_replies": list(item.thread_replies),
                }
                for item in team_updates
            ],
            "industry_stories": industry_story_inputs,
        }

        prompt = self._build_prompt(input_payload)
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for _attempt in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=4096,
            )
            last_output = result.content
            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, PLANNER_SCHEMA)
                return payload
            except ContentValidationError as exc:
                last_error = str(exc)
                prompt = self._build_repair_prompt(
                    original_prompt=prompt,
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
            f"INPUT:\n{json.dumps(payload, indent=2, sort_keys=True)}"
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
