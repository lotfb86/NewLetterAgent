"""Validation helpers for team updates and pre-send content checks."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from jsonschema import ValidationError, validate


class ContentValidationError(ValueError):
    """Raised when generated content fails schema or safety checks."""


def extract_json_payload(raw_text: str) -> dict[str, Any]:
    """Extract and parse JSON object from model output text.

    Uses three strategies in order:
    1. Direct ``json.loads`` on the full text.
    2. Extract from a markdown code fence (````` ```json ... ``` `````).
    3. Brace-depth scanning to find the first balanced ``{…}`` block.
    """
    text = raw_text.strip()
    if not text:
        raise ContentValidationError("Model returned empty response")

    # Strategy 1: the entire response is valid JSON.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 2: markdown code fence (flexible whitespace handling).
    fence_match = re.search(
        r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```",
        text,
    )
    if fence_match:
        inner = fence_match.group(1).strip()
        if inner.startswith("{"):
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    # Strategy 3: find the first balanced {…} block via brace-depth counting.
    # This avoids the greedy regex problem where prose braces cause incorrect
    # extraction boundaries.
    extracted = _extract_first_json_object(text)
    if extracted is None:
        raise ContentValidationError("No JSON object found in model output")

    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ContentValidationError("Invalid JSON in model output") from exc

    if not isinstance(parsed, dict):
        raise ContentValidationError("Top-level JSON payload must be an object")

    return parsed


def _extract_first_json_object(text: str) -> str | None:
    """Find the first balanced ``{…}`` block using brace-depth counting.

    Tracks depth while respecting JSON string literals so that braces
    inside quoted strings are not counted.  Returns *None* if no balanced
    block is found.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for idx in range(start, len(text)):
        char = text[idx]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            if in_string:
                escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : idx + 1]
                # Validate it actually parses before returning.
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    # This balanced block wasn't valid JSON; keep scanning
                    # from the next opening brace.
                    next_start = text.find("{", idx + 1)
                    if next_start == -1:
                        return None
                    return _extract_first_json_object(text[next_start:])

    return None


def validate_json_payload(payload: dict[str, Any], schema: dict[str, object]) -> None:
    """Validate payload against schema and surface clean error messages."""
    try:
        validate(instance=payload, schema=schema)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        context = f" at {path}" if path else ""
        raise ContentValidationError(f"Schema validation failed{context}: {exc.message}") from exc


def validate_https_links(payload: dict[str, Any]) -> list[str]:
    """Validate that all URL fields in payload use https absolute links."""
    errors: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = f"{path}.{key}" if path else key
                if key.endswith("url") and isinstance(value, str):
                    if not _is_https_url(value):
                        errors.append(f"Invalid URL at {next_path}: {value}")
                _walk(value, next_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")

    _walk(payload, "")
    return errors


def validate_rendered_html(html: str) -> list[str]:
    """Run pre-send HTML checks for required sections and link quality."""
    errors: list[str] = []
    if "{{{RESEND_UNSUBSCRIBE_URL}}}" not in html:
        errors.append("Missing unsubscribe placeholder")

    if len(html) > 180_000:
        errors.append("Rendered HTML exceeds size budget")

    soup = BeautifulSoup(html, "html.parser")
    if not soup.find(string=re.compile("What We've Been Up To|The Ruh Digest", re.IGNORECASE)):
        errors.append("Missing required section headers")

    for anchor in soup.find_all("a"):
        href = str(anchor.get("href", "")).strip()
        if not href:
            errors.append("Anchor tag missing href")
            continue
        if href == "{{{RESEND_UNSUBSCRIBE_URL}}}":
            continue
        if not _is_https_url(href):
            errors.append(f"Invalid anchor href: {href}")

    return errors


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)
