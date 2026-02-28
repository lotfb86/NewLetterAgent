"""Data quality checks for canonicalization, trust, and verification."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from models import Confidence, SourceTier, StoryCandidate

logger = logging.getLogger(__name__)

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {
    "ref",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "mkt_tok",
}

_REDIRECT_QUERY_KEYS = ("url", "u", "redirect", "target")

_TIER_1_DOMAINS = {
    "openai.com",
    "anthropic.com",
    "blog.google",
    "ai.google",
    "microsoft.com",
    "meta.com",
}

_TIER_2_DOMAINS = {
    "techcrunch.com",
    "venturebeat.com",
    "news.crunchbase.com",
    "crunchbase.com",
    "wsj.com",
    "bloomberg.com",
    "reuters.com",
    "theverge.com",
}

_NUMERIC_CLAIM_PATTERN = re.compile(
    r"(?:\$\s?\d[\d,.]*(?:\s?[MBKmbk])?|\d[\d,.]*%|\d[\d,.]*(?:\s?[MBKmbk])?)"
)


def canonicalize_url(url: str) -> str:
    """Normalize URLs by removing tracking parameters and wrappers."""
    raw = url.strip()
    if not raw:
        return raw

    parsed = urlparse(raw)
    query_params = parse_qs(parsed.query, keep_blank_values=False)

    redirected = _unwrap_redirect(parsed, query_params)
    if redirected is not None:
        parsed = urlparse(redirected)
        query_params = parse_qs(parsed.query, keep_blank_values=False)

    clean_query: dict[str, list[str]] = {}
    for key, value in query_params.items():
        lowered = key.lower()
        if lowered in _TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES):
            continue
        clean_query[key] = value

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = re.sub(r"//+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            host,
            path,
            "",
            urlencode(clean_query, doseq=True),
            "",
        )
    )


def assign_source_tier(url: str) -> SourceTier:
    """Assign source tier from canonical URL domain."""
    host = urlparse(canonicalize_url(url)).netloc

    if host in _TIER_1_DOMAINS:
        return SourceTier.TIER_1
    if host in _TIER_2_DOMAINS:
        return SourceTier.TIER_2
    return SourceTier.TIER_3


def apply_canonicalization_and_tiering(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    """Canonicalize URLs and align source trust tiers and base confidence."""
    normalized: list[StoryCandidate] = []
    for story in stories:
        canonical_url = canonicalize_url(story.source_url)
        tier = assign_source_tier(canonical_url)
        confidence = _max_confidence(story.confidence, _default_confidence_for_tier(tier))
        normalized.append(
            replace(
                story,
                source_url=canonical_url,
                source_tier=tier,
                confidence=confidence,
                metadata={
                    **story.metadata,
                    "canonical_url": canonical_url,
                    "source_tier": tier.value,
                },
            )
        )
    return normalized


def enforce_numeric_claim_verification(stories: list[StoryCandidate]) -> list[StoryCandidate]:
    """Promote or demote confidence for stories with numeric claims."""
    grouped_by_claim: dict[str, list[StoryCandidate]] = {}
    for story in stories:
        claims = extract_numeric_claims(f"{story.title} {story.summary or ''}")
        if not claims:
            continue
        for claim in claims:
            grouped_by_claim.setdefault(claim, []).append(story)

    verified: list[StoryCandidate] = []
    for story in stories:
        claims = extract_numeric_claims(f"{story.title} {story.summary or ''}")
        if not claims:
            verified.append(story)
            continue

        is_verified = False
        if story.source_tier == SourceTier.TIER_1:
            is_verified = True
        else:
            domains = {
                urlparse(other.source_url).netloc
                for claim in claims
                for other in grouped_by_claim.get(claim, [])
            }
            is_verified = len(domains) >= 2

        if is_verified:
            verified.append(
                replace(
                    story,
                    confidence=Confidence.HIGH,
                    metadata={**story.metadata, "numeric_claims_verified": True},
                )
            )
        else:
            verified.append(
                replace(
                    story,
                    confidence=Confidence.LOW,
                    metadata={
                        **story.metadata,
                        "numeric_claims_verified": False,
                        "verification_note": "numeric claims unverified",
                    },
                )
            )

    return verified


def enforce_recency(
    stories: list[StoryCandidate],
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[StoryCandidate]:
    """Drop stale stories and mark missing-date stories as low-confidence."""
    normalized_start = start_at.astimezone(UTC)
    normalized_end = end_at.astimezone(UTC)

    filtered: list[StoryCandidate] = []
    for story in stories:
        published_at = story.published_at
        if published_at is None:
            filtered.append(
                replace(
                    story,
                    confidence=Confidence.LOW,
                    metadata={
                        **story.metadata,
                        "missing_timestamp": True,
                        "verification_note": "missing published_at",
                    },
                )
            )
            continue

        ts = published_at.astimezone(UTC)
        if ts < normalized_start or ts > normalized_end:
            continue

        filtered.append(story)

    return filtered


def validate_citation_fields(stories: list[StoryCandidate]) -> list[str]:
    """Validate required citation fields for planning and rendering stages."""
    errors: list[str] = []
    for index, story in enumerate(stories):
        if not story.source_url:
            errors.append(f"story[{index}] missing source_url")
        if not story.source_name:
            errors.append(f"story[{index}] missing source_name")
        if story.published_at is None:
            errors.append(f"story[{index}] missing published_at")
        if story.confidence not in {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW}:
            errors.append(f"story[{index}] has invalid confidence")
    return errors


def to_planning_inputs(stories: list[StoryCandidate]) -> list[dict[str, str | int | None]]:
    """Convert stories into planner-ready dictionaries with trust metadata."""
    planning_items: list[dict[str, str | int | None]] = []
    for story in stories:
        planning_items.append(
            {
                "title": story.title,
                "source_url": story.source_url,
                "source_name": story.source_name,
                "published_at": (
                    story.published_at.astimezone(UTC).isoformat()
                    if story.published_at is not None
                    else None
                ),
                "confidence": story.confidence.value,
                "source_tier": story.source_tier.value,
                "summary": story.summary,
            }
        )
    return planning_items


def _default_confidence_for_tier(tier: SourceTier) -> Confidence:
    if tier == SourceTier.TIER_1:
        return Confidence.HIGH
    if tier == SourceTier.TIER_2:
        return Confidence.MEDIUM
    return Confidence.LOW


def _max_confidence(left: Confidence, right: Confidence) -> Confidence:
    ranking = {
        Confidence.LOW: 0,
        Confidence.MEDIUM: 1,
        Confidence.HIGH: 2,
    }
    return left if ranking[left] >= ranking[right] else right


def _resolve_google_news_url(url: str) -> str | None:
    """Resolve a Google News RSS redirect URL via HTTP HEAD.

    Google News RSS article URLs use base64-encoded protobuf paths
    (``/rss/articles/CBMi...``) that cannot be decoded from the URL
    string alone.  An HTTP HEAD with redirect following reveals the
    final destination URL.

    Returns the resolved URL, or ``None`` if resolution fails.
    """
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0 (newsletter-agent)"},
        )
        final_url = response.url
        if final_url and urlparse(final_url).netloc.lower() != "news.google.com":
            return final_url
    except Exception:  # noqa: BLE001
        logger.debug("Failed to resolve Google News URL: %s", url, exc_info=True)
    return None


def _unwrap_redirect(parsed: Any, query_params: dict[str, list[str]]) -> str | None:
    if not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    if host not in {"t.co", "l.facebook.com", "news.google.com"}:
        return None

    # Google News RSS article URLs use path-encoded protobuf, not query params.
    if host == "news.google.com" and "/rss/articles/" in (parsed.path or ""):
        original_url = urlunparse((
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
        return _resolve_google_news_url(original_url)

    for key in _REDIRECT_QUERY_KEYS:
        values = query_params.get(key)
        if values:
            return values[0]
    return None


def extract_numeric_claims(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).replace(" ", "") for match in _NUMERIC_CLAIM_PATTERN.finditer(text))
