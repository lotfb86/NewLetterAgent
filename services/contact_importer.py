"""Bulk contact import service for Resend audience management."""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class ImportResult:
    """Outcome of a bulk contact import operation."""

    imported: int
    duplicates: int
    failures: int
    invalid_emails: tuple[str, ...]
    failed_emails: tuple[str, ...]


class ContactImporter:
    """Parse and import contacts to Resend audience."""

    def __init__(
        self,
        *,
        resend_api_key: str,
        audience_id: str,
        resend_module: Any | None = None,
    ) -> None:
        if resend_module is not None:
            self._resend = resend_module
        else:
            import importlib
            from typing import cast

            mod = cast(Any, importlib.import_module("resend"))
            mod.api_key = resend_api_key
            self._resend = mod
        self._audience_id = audience_id

    def parse_inline(self, text: str) -> tuple[list[str], list[str]]:
        """Parse emails from inline text (comma, newline, or space-separated).

        Returns (valid_emails, invalid_entries).
        """
        # Split on commas, newlines, semicolons, and whitespace
        raw_tokens = re.split(r"[,;\s\n]+", text.strip())
        tokens = [t.strip().lower() for t in raw_tokens if t.strip()]

        valid: list[str] = []
        invalid: list[str] = []

        for token in tokens:
            # Strip angle brackets (e.g. <user@example.com>)
            cleaned = token.strip("<>")
            if EMAIL_PATTERN.match(cleaned):
                valid.append(cleaned)
            else:
                invalid.append(token)

        return valid, invalid

    def parse_csv(self, content: bytes | str) -> tuple[list[str], list[str]]:
        """Parse CSV with an 'email' column.

        Returns (valid_emails, invalid_entries).
        """
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
        else:
            text = content

        reader = csv.DictReader(io.StringIO(text))

        # Find the email column (case-insensitive)
        email_column: str | None = None
        if reader.fieldnames:
            for col in reader.fieldnames:
                if col.strip().lower() == "email":
                    email_column = col
                    break

        if email_column is None:
            raise ValueError(
                "CSV must contain an 'email' column. "
                f"Found columns: {list(reader.fieldnames or [])}"
            )

        valid: list[str] = []
        invalid: list[str] = []

        for row in reader:
            raw_email = (row.get(email_column) or "").strip().lower()
            if not raw_email:
                continue
            if EMAIL_PATTERN.match(raw_email):
                valid.append(raw_email)
            else:
                invalid.append(raw_email)

        return valid, invalid

    def import_contacts(self, emails: list[str]) -> ImportResult:
        """Import a list of validated emails to the Resend audience.

        Returns an ImportResult with counts of imported, duplicate, and failed.
        """
        imported = 0
        duplicates = 0
        failures = 0
        failed_emails: list[str] = []

        for email in emails:
            try:
                self._resend.contacts.create(
                    {
                        "email": email,
                        "audience_id": self._audience_id,
                    }
                )
                imported += 1
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc).lower()
                if "already" in error_text and "exist" in error_text:
                    duplicates += 1
                else:
                    failures += 1
                    failed_emails.append(email)
                    logger.warning("Failed to import contact %s: %s", email, exc)

        return ImportResult(
            imported=imported,
            duplicates=duplicates,
            failures=failures,
            invalid_emails=(),
            failed_emails=tuple(failed_emails),
        )
