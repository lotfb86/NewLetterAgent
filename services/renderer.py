"""Deterministic rendering from newsletter JSON to HTML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from services.schemas import NEWSLETTER_SCHEMA
from services.validator import (
    ContentValidationError,
    validate_https_links,
    validate_json_payload,
    validate_rendered_html,
)


class NewsletterRenderer:
    """Render canonical newsletter JSON via Jinja template."""

    def __init__(self, template_path: Path) -> None:
        self._template_path = template_path
        self._environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, newsletter_payload: dict[str, Any]) -> str:
        """Render validated newsletter JSON into deterministic HTML."""
        self._validate_payload(newsletter_payload)
        template = self._environment.get_template(self._template_path.name)
        html = template.render(**newsletter_payload)

        html_errors = validate_rendered_html(html)
        if html_errors:
            raise ContentValidationError("; ".join(html_errors))
        return html

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        validate_json_payload(payload, NEWSLETTER_SCHEMA)
        link_errors = validate_https_links(payload)
        if link_errors:
            raise ContentValidationError("; ".join(link_errors))
