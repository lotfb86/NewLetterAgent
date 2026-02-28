"""Tests for listeners.intent."""

from __future__ import annotations

from typing import Any

from listeners.intent import IntentClassifier, IntentResult, _parse_intent_response


class _FakeLLM:
    """Fake LLM client that returns predefined content."""

    def __init__(self, content: str) -> None:
        self._content = content

    def ask_claude(self, **_: Any) -> Any:
        return type("Resp", (), {"content": self._content})()


class _FailingLLM:
    """Fake LLM client that raises on every call."""

    def ask_claude(self, **_: Any) -> Any:
        raise RuntimeError("LLM unavailable")


def test_classify_team_update() -> None:
    llm = _FakeLLM('{"intent": "team_update", "response": "TEAM_UPDATE"}')
    classifier = IntentClassifier(llm)  # type: ignore[arg-type]

    result = classifier.classify("We shipped the new dashboard feature this week")

    assert result.intent == "team_update"
    assert result.response == "TEAM_UPDATE"


def test_classify_help_request() -> None:
    llm = _FakeLLM('{"intent": "help_request", "response": "You can use /import-contacts to add subscribers."}')
    classifier = IntentClassifier(llm)  # type: ignore[arg-type]

    result = classifier.classify("How do I add subscribers?")

    assert result.intent == "help_request"
    assert "import-contacts" in result.response


def test_classify_conversation() -> None:
    llm = _FakeLLM('{"intent": "conversation", "response": "Hey there! How can I help?"}')
    classifier = IntentClassifier(llm)  # type: ignore[arg-type]

    result = classifier.classify("Hello!")

    assert result.intent == "conversation"
    assert "help" in result.response.lower()


def test_classify_command_request() -> None:
    llm = _FakeLLM(
        '{"intent": "command_request", "response": "Use `/run` to start a manual research cycle."}'
    )
    classifier = IntentClassifier(llm)  # type: ignore[arg-type]

    result = classifier.classify("run the newsletter")

    assert result.intent == "command_request"
    assert "/run" in result.response


def test_classify_fallback_on_llm_failure() -> None:
    classifier = IntentClassifier(_FailingLLM())  # type: ignore[arg-type]

    result = classifier.classify("anything")

    assert result.intent == "team_update"
    assert result.response == "TEAM_UPDATE"


def test_parse_intent_response_valid_json() -> None:
    result = _parse_intent_response('{"intent": "help_request", "response": "Sure!"}')

    assert result.intent == "help_request"
    assert result.response == "Sure!"


def test_parse_intent_response_json_in_markdown() -> None:
    raw = '```json\n{"intent": "conversation", "response": "Hi!"}\n```'
    result = _parse_intent_response(raw)

    assert result.intent == "conversation"
    assert result.response == "Hi!"


def test_parse_intent_response_invalid_json_fallback() -> None:
    result = _parse_intent_response("This is not JSON at all")

    assert result.intent == "team_update"
    assert result.response == "TEAM_UPDATE"


def test_parse_intent_response_invalid_intent_fallback() -> None:
    result = _parse_intent_response('{"intent": "unknown_type", "response": "Something"}')

    assert result.intent == "team_update"
    assert result.response == "TEAM_UPDATE"


def test_parse_intent_response_empty_string() -> None:
    result = _parse_intent_response("")

    assert result.intent == "team_update"
    assert result.response == "TEAM_UPDATE"


def test_parse_intent_response_with_extra_text() -> None:
    raw = 'Here is my analysis:\n{"intent": "help_request", "response": "Try /help"}\nThat should work.'
    result = _parse_intent_response(raw)

    assert result.intent == "help_request"
    assert result.response == "Try /help"
