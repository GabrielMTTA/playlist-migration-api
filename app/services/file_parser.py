"""File parser — reads .txt files and produces domain Track objects.

Supports two formats per line:
  1. "Artist - Title"
  2. "Title" (artist left as None)

Security: all inputs are sanitized (stripped, truncated, null-byte removed).
"""

import re

from app.domain.models import Track

# Max limits to prevent abuse
MAX_LINES = 500
MAX_LINE_LENGTH = 300

# Regex to strip control characters (except common whitespace)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_line(line: str) -> str:
    """Remove control characters and enforce length limit."""
    clean = _CONTROL_CHARS.sub("", line).strip()
    return clean[:MAX_LINE_LENGTH]


def _parse_line(line: str) -> Track | None:
    """Parse a single sanitized line into a Track.

    Returns None if the line is empty or a comment.
    """
    sanitized = _sanitize_line(line)

    if not sanitized or sanitized.startswith("#"):
        return None

    # Try "Artist - Title" format (first occurrence of " - ")
    if " - " in sanitized:
        parts = sanitized.split(" - ", maxsplit=1)
        artist = parts[0].strip()
        title = parts[1].strip()
        if title:
            return Track(raw_input=sanitized, title=title, artist=artist or None)

    # Fallback: entire line is the title
    return Track(raw_input=sanitized, title=sanitized)


def parse_file_content(content: str) -> list[Track]:
    """Parse raw text content into a list of Track objects.

    Args:
        content: Raw text content (utf-8) from uploaded file.

    Returns:
        List of parsed tracks (up to MAX_LINES).

    Raises:
        ValueError: If no valid tracks are found.
    """
    lines = content.splitlines()[:MAX_LINES]
    tracks = [track for line in lines if (track := _parse_line(line)) is not None]

    if not tracks:
        raise ValueError("No valid tracks found in file")

    return tracks
