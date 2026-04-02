"""Fuzzy matching service — validates Spotify search results against user input.

Uses RapidFuzz for high-performance string similarity scoring.
Three strategies are combined into a weighted confidence score:

  1. Full-string ratio (title + artist vs. result name + artist)
  2. Token-sort ratio (order-insensitive comparison)
  3. Partial ratio (substring matching for abbreviated inputs)
"""

import re
import unicodedata

from rapidfuzz import fuzz

# Minimum confidence threshold to consider a match valid
DEFAULT_CONFIDENCE_THRESHOLD = 60.0

# Weights for the composite score
_WEIGHT_FULL = 0.45
_WEIGHT_TOKEN_SORT = 0.35
_WEIGHT_PARTIAL = 0.20

# Regex: strip content in parentheses/brackets (remix tags, feat., etc.)
_EXTRA_INFO = re.compile(r"\s*[\(\[\{].*?[\)\]\}]\s*")
# Non-alphanumeric (keep spaces)
_NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    """Normalize a string for comparison.

    - Lowercase
    - Unicode NFKD normalization (accents removed)
    - Strip parenthetical info (remixes, feat., etc.)
    - Remove non-alphanumeric characters
    - Collapse whitespace
    """
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _EXTRA_INFO.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def compute_confidence(
    input_title: str,
    input_artist: str | None,
    result_title: str,
    result_artist: str,
) -> float:
    """Compute a composite confidence score (0–100) between input and result.

    Args:
        input_title: Title from the user's input.
        input_artist: Artist from user's input (may be None).
        result_title: Track name returned by the platform.
        result_artist: Artist name returned by the platform.

    Returns:
        Confidence score from 0.0 to 100.0.
    """
    # Build comparison strings
    input_str = normalize(input_title)
    result_str = normalize(result_title)

    if input_artist:
        input_full = f"{normalize(input_artist)} {input_str}"
    else:
        input_full = input_str

    result_full = f"{normalize(result_artist)} {result_str}"

    # Strategy 1: Full string ratio
    full_score = fuzz.ratio(input_full, result_full)

    # Strategy 2: Token-sort ratio (order doesn't matter)
    token_sort_score = fuzz.token_sort_ratio(input_full, result_full)

    # Strategy 3: Partial ratio (handles abbreviations/substrings)
    partial_score = fuzz.partial_ratio(input_str, result_str)

    composite = (
        full_score * _WEIGHT_FULL
        + token_sort_score * _WEIGHT_TOKEN_SORT
        + partial_score * _WEIGHT_PARTIAL
    )

    return round(composite, 2)


def pick_best_match(
    input_title: str,
    input_artist: str | None,
    candidates: list[dict],
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[dict | None, float]:
    """Select the best matching candidate above the confidence threshold.

    Args:
        input_title: Title from user input.
        input_artist: Artist from user input (may be None).
        candidates: List of Spotify track items (dicts with 'name', 'artists').
        threshold: Minimum confidence to accept a match.

    Returns:
        Tuple of (best_candidate_or_None, confidence_score).
    """
    best_candidate: dict | None = None
    best_score: float = 0.0

    for candidate in candidates:
        result_title = candidate.get("name", "")
        artists = candidate.get("artists", [])
        result_artist = artists[0]["name"] if artists else ""

        score = compute_confidence(
            input_title, input_artist, result_title, result_artist,
        )

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_score >= threshold:
        return best_candidate, best_score

    return None, best_score
