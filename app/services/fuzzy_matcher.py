"""Fuzzy matching service — validates search results against user input.

Uses RapidFuzz for high-performance string similarity scoring.
Three strategies are combined into a weighted confidence score:

  1. Full-string ratio (title + artist vs. result name + artist)
  2. Token-sort ratio (order-insensitive comparison)
  3. Partial ratio (substring matching for abbreviated inputs)
"""

import re
import unicodedata

from rapidfuzz import fuzz

from app.domain.models import MatchCandidate

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

# Version keywords — used to penalize mismatched versions
_LIVE_KEYWORDS = re.compile(
    r"\b(live|ao vivo|live at|live from|live session|live performance)\b",
    re.IGNORECASE,
)
_ACOUSTIC_KEYWORDS = re.compile(r"\bacoustic\b", re.IGNORECASE)
_REMIX_KEYWORDS = re.compile(r"\bremix\b", re.IGNORECASE)
_LYRICS_KEYWORDS = re.compile(
    r"\b(lyrics|lyric video|letra|legendado)\b",
    re.IGNORECASE,
)
_TRANSLATION_KEYWORDS = re.compile(
    r"\b(tradu[çc][ãa]o|traduzid[ao]|translated|perevodom)\b",
    re.IGNORECASE,
)

# Penalty multipliers when candidate version doesn't match input intent
_HARD_PENALTY = 0.5   # Live, Acoustic, Remix — musically different versions
_SOFT_PENALTY = 0.85  # Lyrics, Translation — same music, visual overlay only


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


def _version_penalty(input_text: str, candidate_title: str) -> float:
    """Return a penalty multiplier (0.0–1.0) for version mismatches.

    If the candidate is a live/acoustic/remix/lyrics/translation version
    but the input doesn't ask for it (or vice-versa), the score is penalized.

    Hard penalty (0.5): live, acoustic, remix — musically different.
    Soft penalty (0.7): lyrics, translation — same music, visual overlay.

    Returns:
        1.0 (no penalty), _HARD_PENALTY, or _SOFT_PENALTY.
    """
    # Hard penalty group — musically different versions
    for pattern in (_LIVE_KEYWORDS, _ACOUSTIC_KEYWORDS, _REMIX_KEYWORDS):
        input_has = bool(pattern.search(input_text))
        candidate_has = bool(pattern.search(candidate_title))

        if candidate_has and not input_has:
            return _HARD_PENALTY
        if input_has and not candidate_has:
            return _HARD_PENALTY

    # Soft penalty group — same music, different presentation
    for pattern in (_LYRICS_KEYWORDS, _TRANSLATION_KEYWORDS):
        input_has = bool(pattern.search(input_text))
        candidate_has = bool(pattern.search(candidate_title))

        if candidate_has and not input_has:
            return _SOFT_PENALTY
        if input_has and not candidate_has:
            return _SOFT_PENALTY

    return 1.0


def pick_best_match(
    input_title: str,
    input_artist: str | None,
    candidates: list[MatchCandidate],
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[MatchCandidate | None, float]:
    """Select the best matching candidate above the confidence threshold.

    Args:
        input_title: Title from user input.
        input_artist: Artist from user input (may be None).
        candidates: Platform-agnostic MatchCandidate list.
        threshold: Minimum confidence to accept a match.

    Returns:
        Tuple of (best_candidate_or_None, confidence_score).
    """
    best_candidate: MatchCandidate | None = None
    best_score: float = 0.0

    # Build full input text for version detection
    input_text = f"{input_artist or ''} {input_title}".strip()

    for candidate in candidates:
        score = compute_confidence(
            input_title, input_artist, candidate.title, candidate.artist,
        )

        # Penalize version mismatches (live, acoustic, remix)
        penalty = _version_penalty(input_text, candidate.title)
        score *= penalty

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_score >= threshold:
        return best_candidate, best_score

    return None, best_score
