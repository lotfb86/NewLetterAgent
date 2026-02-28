"""Tests for content validator helpers."""

from __future__ import annotations

import pytest

from services.validator import (
    ContentValidationError,
    extract_json_payload,
    validate_https_links,
    validate_json_payload,
    validate_rendered_html,
)


def test_extract_json_payload_from_wrapped_text() -> None:
    payload = extract_json_payload('prefix {"a": 1} suffix')
    assert payload == {"a": 1}


def test_extract_json_payload_direct_json() -> None:
    payload = extract_json_payload('{"key": "value"}')
    assert payload == {"key": "value"}


def test_extract_json_payload_from_code_fence() -> None:
    text = "Here is the plan:\n```json\n{\"a\": 1, \"b\": 2}\n```\nDone."
    payload = extract_json_payload(text)
    assert payload == {"a": 1, "b": 2}


def test_extract_json_payload_from_code_fence_no_newline() -> None:
    text = "```json{\"a\": 1}```"
    payload = extract_json_payload(text)
    assert payload == {"a": 1}


def test_extract_json_payload_prose_with_braces_before_json() -> None:
    """Prose containing {curly} braces before real JSON shouldn't confuse parser."""
    text = (
        'The plan: {hook here} for the industry.\n'
        '{"team_section": {"include": true}, "cta": {"text": "hi"}}'
    )
    payload = extract_json_payload(text)
    assert payload["team_section"]["include"] is True


def test_extract_json_payload_nested_json() -> None:
    text = 'prefix {"outer": {"inner": [1, 2, 3]}} suffix'
    payload = extract_json_payload(text)
    assert payload == {"outer": {"inner": [1, 2, 3]}}


def test_extract_json_payload_with_escaped_quotes() -> None:
    text = '{"text": "He said \\"hello\\" today"}'
    payload = extract_json_payload(text)
    assert payload["text"] == 'He said "hello" today'


def test_extract_json_payload_raises_for_invalid() -> None:
    with pytest.raises(ContentValidationError):
        extract_json_payload("no json here")


def test_validate_json_payload_with_minimal_schema() -> None:
    validate_json_payload({"a": "x"}, {"type": "object", "required": ["a"]})


def test_validate_https_links_flags_non_https() -> None:
    errors = validate_https_links({"cta": {"url": "http://example.com"}})
    assert errors


def test_validate_rendered_html_checks_unsubscribe_and_links() -> None:
    errors = validate_rendered_html("<html><body><a href='http://bad.com'>x</a></body></html>")
    assert any("unsubscribe" in error.lower() for error in errors)
    assert any("invalid anchor" in error.lower() for error in errors)
