"""Published story memory read/write helpers."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_fcntl: Any
try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover
    _fcntl = None

fcntl: Any = _fcntl


_HEADER = "# Published Newsletter Stories\n\n"


@dataclass(frozen=True)
class PublishedStory:
    """A single published story entry stored in the brain file."""

    issue_date: str
    title: str
    url: str


def ensure_brain_file(path: Path) -> None:
    """Ensure the brain file and parent directory exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write(path, _HEADER)


def append_published_stories(
    path: Path,
    issue_date: str,
    stories: Sequence[tuple[str, str]],
) -> None:
    """Append stories for an issue date using file lock + atomic replace."""
    if not stories:
        return

    ensure_brain_file(path)

    with _exclusive_lock(path):
        current = path.read_text(encoding="utf-8")
        if not current.strip():
            current = _HEADER

        block_lines = [f"## {issue_date}\n"]
        for title, url in stories:
            block_lines.append(f"- {title} | {url}\n")
        block_lines.append("\n")
        updated = current
        if not updated.endswith("\n"):
            updated += "\n"
        updated += "".join(block_lines)
        _atomic_write(path, updated)


def read_published_stories(path: Path) -> list[PublishedStory]:
    """Parse published stories from the markdown memory file."""
    if not path.exists():
        return []

    entries: list[PublishedStory] = []
    current_date: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_date = line.removeprefix("## ").strip()
            continue
        if not line.startswith("- ") or current_date is None:
            continue

        payload = line.removeprefix("- ")
        if " | " not in payload:
            continue
        title, url = payload.split(" | ", 1)
        entries.append(
            PublishedStory(
                issue_date=current_date,
                title=title.strip(),
                url=url.strip(),
            )
        )

    return entries


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Acquire an exclusive advisory lock for the brain file."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, content: str) -> None:
    """Write file content atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
    ) as temp_file:
        temp_file.write(content)
        temp_name = temp_file.name
    os.replace(temp_name, path)
