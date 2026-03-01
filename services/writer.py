"""Newsletter content generation to canonical JSON."""

from __future__ import annotations

import json
import logging
from typing import Any

from config import AppConfig
from services.composition import CompositionFailure, save_composition_dead_letter
from services.llm import OpenRouterClient
from services.schemas import NEWSLETTER_SCHEMA
from services.validator import ContentValidationError, extract_json_payload, validate_json_payload

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = (
    "You are the writer of The Ruh Digest — a weekly AI industry newsletter "
    "that people actually look forward to reading. Published by Ruh.ai, which "
    "builds human emulators and AI digital employees for enterprise clients.\n\n"
    "Your readers are sharp people — executives, investors, builders — who are "
    "drowning in AI news. Your job is to be the one newsletter they open first "
    "because it's genuinely fun to read AND makes them smarter.\n\n"
    "Output ONLY a single JSON object. "
    "Do NOT include markdown code fences, commentary, or any text "
    "before or after the JSON object."
)

VOICE_STYLE_GUIDE = (
    "YOUR VOICE:\n"
    "You're a sharp, well-read friend who's obsessed with AI and can't help "
    "making it interesting. You explain complex things simply, you notice what's "
    "actually important vs. what's just noise, and you have a dry wit about "
    "the absurdity of the hype cycle. You're never cynical — you genuinely love "
    "this stuff — but you're allergic to bullshit.\n\n"

    "WRITING RULES:\n"
    "1. Write at a 7th-grade reading level. Use contractions. Short sentences. "
    "Active voice. Strong verbs instead of adverbs.\n"
    "2. Every story opens with the most interesting thing — not background. "
    "Lead with what made you say 'wait, what?' and explain after.\n"
    "3. Humor comes from observation, not jokes. Notice absurd juxtapositions, "
    "deadpan understatement, and the gap between what companies say and what "
    "they actually do. Never force it.\n"
    "4. 'Why it matters' should be an actual opinion, not a summary. Tell the "
    "reader what this means for their world. Be specific.\n"
    "5. Vary the energy. One story can be a quick hit (2 sentences). The next "
    "can go deeper. Rhythm matters.\n"
    "6. Facts are sacred. Humor never changes numbers, dates, sources, or "
    "confidence labels. Use 'reportedly' when confidence is not high.\n\n"

    "FIELD-SPECIFIC GUIDANCE:\n"
    "- subject_line: 6-10 words. Create a curiosity gap. Never 'This Week in AI' "
    "or anything generic. Make them click.\n"
    "- preheader: One punchy sentence that complements (doesn't repeat) the subject line.\n"
    "- intro: 2-3 sentences max. Set the vibe for the whole issue. Can be an "
    "observation, a question, or a bold claim. No throat-clearing.\n"
    "- headline: The angle, not the summary. 'Google's AI Can Now Book Your "
    "Dentist' beats 'Google Releases New AI Agent Features'. 7-10 words.\n"
    "- hook: The most interesting detail, delivered like you're telling a friend. "
    "Start with the surprise, not the setup.\n"
    "- why_it_matters: Your actual take. What does this mean for people building "
    "with AI? For enterprises? For the industry? Be opinionated.\n\n"

    "BANNED WORDS (these scream 'AI wrote this'):\n"
    "delve, tapestry, landscape, leverage, pivotal, robust, crucial, moreover, "
    "furthermore, utilize, facilitate, paradigm, synergy, ecosystem, holistic, "
    "cutting-edge, groundbreaking, revolutionize, game-changer, deep dive, "
    "unpack, at the end of the day, it's worth noting, in today's rapidly "
    "evolving, the AI space, moving forward, key takeaway, let's dive in.\n\n"

    "SAFETY:\n"
    "- Punch up at hype and absurd trends, never down at people.\n"
    "- Never mock readers, companies, founders, or vulnerable groups.\n"
    "- Keep claims precise. When in doubt, hedge.\n"
)

NEWSLETTER_JSON_SCHEMA_SNIPPET = (
    "Return a JSON object with this exact structure (no extra keys):\n"
    "{\n"
    '  "newsletter_name": "The Ruh Digest",\n'
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

        initial_prompt = self._build_prompt(input_payload)
        prompt = initial_prompt
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for attempt_num in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=WRITER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.5,
                max_tokens=16384,
            )
            last_output = result.content
            logger.info(
                "Writer attempt %d/%d: model returned %d chars (first 200: %r)",
                attempt_num,
                attempts,
                len(result.content),
                result.content[:200],
            )

            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, NEWSLETTER_SCHEMA)
                return payload
            except ContentValidationError as exc:
                last_error = str(exc)
                logger.warning(
                    "Writer attempt %d/%d failed: %s",
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
        initial_prompt = (
            "You are revising an existing newsletter JSON payload.\n"
            "Apply only the requested feedback while preserving unchanged sections.\n"
            "Preserve the voice target and safety rules below while revising.\n\n"
            f"{VOICE_STYLE_GUIDE}\n"
            "Return valid JSON only and keep all required schema fields.\n"
            f"{NEWSLETTER_JSON_SCHEMA_SNIPPET}\n"
            f"INPUT:\n{json.dumps(input_payload, indent=2, sort_keys=True)}\n\n"
            "IMPORTANT: Respond ONLY with the JSON object. "
            "Do not include any explanation, commentary, or markdown formatting. "
            "Start your response with { and end with }."
        )
        prompt = initial_prompt
        attempts = self._config.max_external_retries
        last_error = "unknown"
        last_output: str | None = None

        for attempt_num in range(1, attempts + 1):
            result = self._llm_client.ask_claude(
                system_prompt=WRITER_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.5,
                max_tokens=16384,
            )
            last_output = result.content
            logger.info(
                "Writer revision attempt %d/%d: model returned %d chars",
                attempt_num,
                attempts,
                len(result.content),
            )
            try:
                payload = extract_json_payload(result.content)
                validate_json_payload(payload, NEWSLETTER_SCHEMA)
                return payload
            except ContentValidationError as exc:
                last_error = str(exc)
                logger.warning(
                    "Writer revision attempt %d/%d failed: %s",
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
            "Write the weekly newsletter JSON from the planning payload.\n\n"
            f"{VOICE_STYLE_GUIDE}\n"
            "STRUCTURAL RULES:\n"
            "- Include exactly 6 to 8 industry stories. Pick only the best from the plan.\n"
            "- Preserve confidence metadata exactly as given for every story.\n"
            "- All source_url values must be absolute https links copied from the plan.\n"
            "- CTA should invite readers to explore AI employee solutions at https://ruh.ai "
            "or to get in touch about investment opportunities.\n"
            "- The entire newsletter should be readable in under 5 minutes.\n\n"
            f"{NEWSLETTER_JSON_SCHEMA_SNIPPET}\n"
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
