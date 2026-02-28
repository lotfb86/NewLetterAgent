"""Tests for services.contact_importer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.contact_importer import ContactImporter, ImportResult


@pytest.fixture
def importer() -> ContactImporter:
    mock_resend = MagicMock()
    return ContactImporter(
        resend_api_key="re_test",
        audience_id="aud_test",
        resend_module=mock_resend,
    )


def test_parse_inline_comma_separated(importer: ContactImporter) -> None:
    valid, invalid = importer.parse_inline("alice@example.com, bob@example.com, charlie@example.com")

    assert valid == ["alice@example.com", "bob@example.com", "charlie@example.com"]
    assert invalid == []


def test_parse_inline_newline_separated(importer: ContactImporter) -> None:
    valid, invalid = importer.parse_inline("alice@example.com\nbob@example.com")

    assert valid == ["alice@example.com", "bob@example.com"]
    assert invalid == []


def test_parse_inline_mixed_with_invalid(importer: ContactImporter) -> None:
    valid, invalid = importer.parse_inline("good@example.com, not-an-email, ok@test.io")

    assert valid == ["good@example.com", "ok@test.io"]
    assert invalid == ["not-an-email"]


def test_parse_inline_angle_brackets(importer: ContactImporter) -> None:
    valid, invalid = importer.parse_inline("<alice@example.com>, <bob@example.com>")

    assert valid == ["alice@example.com", "bob@example.com"]
    assert invalid == []


def test_parse_inline_lowercases_emails(importer: ContactImporter) -> None:
    valid, _ = importer.parse_inline("Alice@Example.COM")

    assert valid == ["alice@example.com"]


def test_parse_csv_with_email_column(importer: ContactImporter) -> None:
    csv_content = "name,email,role\nAlice,alice@example.com,eng\nBob,bob@test.io,pm\n"

    valid, invalid = importer.parse_csv(csv_content)

    assert valid == ["alice@example.com", "bob@test.io"]
    assert invalid == []


def test_parse_csv_case_insensitive_header(importer: ContactImporter) -> None:
    csv_content = "Name,Email,Notes\nAlice,alice@example.com,hi\n"

    valid, invalid = importer.parse_csv(csv_content)

    assert valid == ["alice@example.com"]
    assert invalid == []


def test_parse_csv_with_invalid_emails(importer: ContactImporter) -> None:
    csv_content = "email\ngood@example.com\nbad-email\nok@test.io\n"

    valid, invalid = importer.parse_csv(csv_content)

    assert valid == ["good@example.com", "ok@test.io"]
    assert invalid == ["bad-email"]


def test_parse_csv_missing_email_column(importer: ContactImporter) -> None:
    csv_content = "name,phone\nAlice,555-1234\n"

    with pytest.raises(ValueError, match="email"):
        importer.parse_csv(csv_content)


def test_parse_csv_bytes_input(importer: ContactImporter) -> None:
    csv_bytes = b"email\nalice@example.com\n"

    valid, invalid = importer.parse_csv(csv_bytes)

    assert valid == ["alice@example.com"]
    assert invalid == []


def test_import_contacts_success(importer: ContactImporter) -> None:
    importer._resend.contacts.create = MagicMock(return_value={"id": "123"})

    result = importer.import_contacts(["a@test.com", "b@test.com"])

    assert result.imported == 2
    assert result.duplicates == 0
    assert result.failures == 0
    assert importer._resend.contacts.create.call_count == 2


def test_import_contacts_handles_duplicates(importer: ContactImporter) -> None:
    def _side_effect(params: dict) -> dict:
        if params["email"] == "existing@test.com":
            raise Exception("Contact already exists")
        return {"id": "123"}

    importer._resend.contacts.create = MagicMock(side_effect=_side_effect)

    result = importer.import_contacts(["existing@test.com", "new@test.com"])

    assert result.imported == 1
    assert result.duplicates == 1
    assert result.failures == 0


def test_import_contacts_handles_failures(importer: ContactImporter) -> None:
    def _side_effect(params: dict) -> dict:
        if params["email"] == "fail@test.com":
            raise Exception("network error")
        return {"id": "123"}

    importer._resend.contacts.create = MagicMock(side_effect=_side_effect)

    result = importer.import_contacts(["fail@test.com", "ok@test.com"])

    assert result.imported == 1
    assert result.failures == 1
    assert result.failed_emails == ("fail@test.com",)


def test_import_result_empty_list(importer: ContactImporter) -> None:
    result = importer.import_contacts([])

    assert result.imported == 0
    assert result.duplicates == 0
    assert result.failures == 0
