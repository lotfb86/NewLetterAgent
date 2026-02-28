"""Tests for services.brain."""

from __future__ import annotations

from pathlib import Path

from services.brain import append_published_stories, ensure_brain_file, read_published_stories


def test_ensure_brain_file_creates_header(tmp_path: Path) -> None:
    brain_path = tmp_path / "published_stories.md"

    ensure_brain_file(brain_path)

    assert brain_path.exists()
    assert brain_path.read_text(encoding="utf-8").startswith("# Published Newsletter Stories")


def test_append_and_read_published_stories(tmp_path: Path) -> None:
    brain_path = tmp_path / "published_stories.md"

    append_published_stories(
        brain_path,
        "2026-02-27",
        [
            ("Story A", "https://example.com/a"),
            ("Story B", "https://example.com/b"),
        ],
    )
    append_published_stories(
        brain_path,
        "2026-03-06",
        [("Story C", "https://example.com/c")],
    )

    entries = read_published_stories(brain_path)

    assert len(entries) == 3
    assert entries[0].issue_date == "2026-02-27"
    assert entries[2].title == "Story C"
