"""Newsletter content generation to canonical JSON."""

from __future__ import annotations

import json
from typing import Any

from config import AppConfig
from services.composition import CompositionFailure, save_composition_dead_letter
from services.llm import OpenRouterClient
from services.schemas import NEWSLETTER_SCHEMA
from services.validator import ContentValidationError, extract_json_payload, validate_json_payload

WRITER_SYSTEM_PROMPT = (
    "You are a newsletter writer. "
    "Output ONLY a single JSON object. "
    "Do NOT include markdown code fences, commentary, or any text "
    "before or after the JSON object."
)

VOICE_STYLE_GUIDE = (
    "VOICE TARGET (blend):\n"
    "- Human, conversational, and emotionally intelligent (YNAB-like warmth).\n"
    "- Funny and witty with punchy phrasing (Milk Road-like energy).\n"
    "- Light sarcasm is allowed occasionally, but never mean-spirited.\n"
    "- Highly relatable: use plain language and everyday analogies.\n"
    "- Entertaining to read while staying credible for clients and investors.\n"
    "VOICE SAFETY RULES:\n"
    "- Humor must never change facts, numbers, dates, sources, or confidence labels.\n"
    "- Punch up at hype and absurd trends, never punch down at people.\n"
    "- Never mock readers, companies, founders, or vulnerable groups.\n"
    "- Avoid forced jokes in every sentence; keep humor natural and selective.\n"
    "- Keep claims precise, and use 'reportedly' framing where confidence is not high.\n"
)

NEWSLETTER_JSON_SCHEMA_SNIPPET = (
    "Return a JSON object with this exact structure (no extra keys):\n"
    "{\n"
    '  "newsletter_name": "This Week in AI",\n'
    '  "issue_date": "2026-02-28",\n'
    '  "subject_line": "...",\n'
    '  "preheader": "...",\n'
    '  "intro": "...",\n'
    '  "team_updates": [{"title": "...", "summary": "..."}],\n'
    '  "industry_stories": [{\n'
    '    "headline": "...", "hook": "...",\n'
    '    "why_it_matters": "...",\n'
    '    "source_url": "https://...", "source_name": "...",\n'
    '    "published_at": "2026-02-28",\n'
    '    "confidence": "high|medium|low"\n'
    "  }],\n"
    '  "cta": {"text": "...", "url": "https://..."}\n'
    "}\n"
)


class NewsletterWriter:
    """Generate newsletter JSON from planner output."""

    def __init__(self, config: AppConfig, llm_client: OpenRouterClient) -> None:
        self._config = config
        self._llm_client = llm_client

    def write_newsletter(
        self,
        *,
        newsletter_plan: dict[str, Any],
        issue_date: str,
        newsletter_name: str,
    ) -> dict[str, Any]:
        """Generate and validate newsletter JSON content."""
        input_payload = {
            "newsletter_name": newsletter_name,
            "issue_date": issue_date,
            "plan": newsletter_plan,
        }

        prompt = self._build_prompt(input_payload)
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for _attempt in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=WRITER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            last_output = result.content

            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, NEWSLETTER_SCHEMA)
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
            stage="writer",
            attempts=attempts,
            error_summary=last_error,
            input_payload=input_payload,
            last_model_output=last_output,
        )
        raise CompositionFailure(
            stage="writer",
            attempts=attempts,
            error_summary=last_error,
            dead_letter_path=dead_letter,
        )

    def revise_newsletter(
        self,
        *,
        current_draft: dict[str, Any],
        feedback_text: str,
    ) -> dict[str, Any]:
        """Revise existing newsletter JSON in response to Slack feedback."""
        input_payload = {
            "current_draft": current_draft,
            "feedback": feedback_text,
        }
        prompt = (
            "You are revising an existing newsletter JSON payload.\n"
            "Apply only the requested feedback while preserving unchanged sections.\n"
            "Preserve the voice target and safety rules below while revising.\n\n"
            f"{VOICE_STYLE_GUIDE}\n"
            "Return valid JSON only and keep all required schema fields.\n"
            f"{NEWSLETTER_JSON_SCHEMA_SNIPPET}\n"
            f"INPUT:\n{json.dumps(input_payload, indent=2, sort_keys=True)}"
        )
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for _attempt in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=WRITER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            last_output = result.content
            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, NEWSLETTER_SCHEMA)
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
            stage="writer_revision",
            attempts=attempts,
            error_summary=last_error,
            input_payload=input_payload,
            last_model_output=last_output,
        )
        raise CompositionFailure(
            stage="writer_revision",
            attempts=attempts,
            error_summary=last_error,
            dead_letter_path=dead_letter,
        )

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        return (
            "Write the weekly newsletter JSON from the planning payload.\n"
            "RULES:\n"
            "- Preserve confidence metadata for every industry story.\n"
            "- Ensure all source URLs are absolute https links.\n"
            "- CTA should include text and a valid https URL.\n"
            "- Keep writing concise enough for a newsletter, but not sterile.\n\n"
            f"{VOICE_STYLE_GUIDE}\n"
            f"{NEWSLETTER_JSON_SCHEMA_SNIPPET}\n"
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
