"""JSON schemas for planner and writer outputs."""

from __future__ import annotations

PLANNER_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["team_section", "industry_section", "cta"],
    "additionalProperties": False,
    "properties": {
        "team_section": {
            "type": "object",
            "required": ["include", "items"],
            "additionalProperties": False,
            "properties": {
                "include": {"type": "boolean"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "summary"],
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                    },
                },
            },
        },
        "industry_section": {
            "type": "object",
            "required": ["items"],
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": [
                            "headline",
                            "hook",
                            "why_it_matters",
                            "source_url",
                            "source_name",
                            "published_at",
                            "confidence",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "headline": {"type": "string"},
                            "hook": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                            "source_url": {"type": "string"},
                            "source_name": {"type": "string"},
                            "published_at": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                        },
                    },
                },
            },
        },
        "cta": {
            "type": "object",
            "required": ["text"],
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
            },
        },
    },
}


NEWSLETTER_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": [
        "newsletter_name",
        "issue_date",
        "subject_line",
        "preheader",
        "intro",
        "team_updates",
        "industry_stories",
        "cta",
    ],
    "additionalProperties": False,
    "properties": {
        "newsletter_name": {"type": "string"},
        "issue_date": {"type": "string"},
        "subject_line": {"type": "string"},
        "preheader": {"type": "string"},
        "intro": {"type": "string"},
        "team_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "summary"],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
        "industry_stories": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "headline",
                    "hook",
                    "why_it_matters",
                    "source_url",
                    "source_name",
                    "published_at",
                    "confidence",
                ],
                "additionalProperties": False,
                "properties": {
                    "headline": {"type": "string"},
                    "hook": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_name": {"type": "string"},
                    "published_at": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
            },
        },
        "cta": {
            "type": "object",
            "required": ["text", "url"],
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    },
}
