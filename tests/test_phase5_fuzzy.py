"""Phase 5 — Fuzzy Matching Intelligence Tests."""

import pytest

from app.domain.models import Track, TrackStatus
from app.services.fuzzy_matcher import (
    compute_confidence,
    normalize,
    pick_best_match,
)
from app.services.spotify_client import SpotifyClient


# ═══════════════════════════════════════════════════
#  Normalization
# ═══════════════════════════════════════════════════

class TestNormalize:
    def test_lowercases(self) -> None:
        assert normalize("HELLO WORLD") == "hello world"

    def test_removes_accents(self) -> None:
        assert normalize("Beyoncé") == "beyonce"
        assert normalize("Édith Piaf") == "edith piaf"

    def test_strips_parenthetical_info(self) -> None:
        assert normalize("Creep (Acoustic Version)") == "creep"
        assert normalize("Song [Remastered 2021]") == "song"
        assert normalize("Track {Live}") == "track"

    def test_removes_punctuation(self) -> None:
        assert normalize("rock & roll") == "rock roll"
        assert normalize("it's a-ok!") == "it s a ok"

    def test_collapses_whitespace(self) -> None:
        assert normalize("  too   many   spaces  ") == "too many spaces"

    def test_handles_empty_string(self) -> None:
        assert normalize("") == ""

    def test_combined_normalization(self) -> None:
        result = normalize("Beyoncé - Crazy in Love (feat. JAY-Z) [Remastered]")
        assert result == "beyonce crazy in love"


# ═══════════════════════════════════════════════════
#  Confidence Scoring
# ═══════════════════════════════════════════════════

class TestComputeConfidence:
    def test_exact_match_high_score(self) -> None:
        score = compute_confidence("Creep", "Radiohead", "Creep", "Radiohead")
        assert score >= 95.0

    def test_different_tracks_low_score(self) -> None:
        score = compute_confidence(
            "Bohemian Rhapsody", "Queen",
            "Under Pressure", "David Bowie",
        )
        assert score < 50.0

    def test_similar_title_different_artist(self) -> None:
        score = compute_confidence(
            "Angel", "Shaggy",
            "Angel", "Massive Attack",
        )
        # Title matches but artist doesn't — moderate score
        assert 40.0 < score < 90.0

    def test_accent_insensitive(self) -> None:
        score = compute_confidence("Beyonce", None, "Beyoncé", "Beyoncé")
        assert score >= 60.0

    def test_remaster_tag_ignored(self) -> None:
        score = compute_confidence(
            "Imagine", "John Lennon",
            "Imagine (Remastered 2010)", "John Lennon",
        )
        assert score >= 85.0

    def test_no_artist_input(self) -> None:
        score = compute_confidence(
            "Smells Like Teen Spirit", None,
            "Smells Like Teen Spirit", "Nirvana",
        )
        assert score >= 60.0

    def test_word_order_tolerance(self) -> None:
        score = compute_confidence(
            "Teen Spirit Like Smells", None,
            "Smells Like Teen Spirit", "Nirvana",
        )
        # Token sort ratio should help here
        assert score >= 50.0


# ═══════════════════════════════════════════════════
#  Best Match Picker
# ═══════════════════════════════════════════════════

class TestPickBestMatch:
    CANDIDATES = [
        {
            "id": "1",
            "uri": "spotify:track:1",
            "name": "Creep",
            "artists": [{"name": "Radiohead"}],
        },
        {
            "id": "2",
            "uri": "spotify:track:2",
            "name": "Creep",
            "artists": [{"name": "Stone Temple Pilots"}],
        },
        {
            "id": "3",
            "uri": "spotify:track:3",
            "name": "Karma Police",
            "artists": [{"name": "Radiohead"}],
        },
    ]

    def test_picks_exact_match(self) -> None:
        match, score = pick_best_match("Creep", "Radiohead", self.CANDIDATES)
        assert match is not None
        assert match["id"] == "1"
        assert score >= 90.0

    def test_picks_correct_artist(self) -> None:
        match, score = pick_best_match(
            "Creep", "Stone Temple Pilots", self.CANDIDATES,
        )
        assert match is not None
        assert match["id"] == "2"

    def test_returns_none_below_threshold(self) -> None:
        match, score = pick_best_match(
            "Completely Different Song", "Unknown Artist",
            self.CANDIDATES,
            threshold=90.0,
        )
        assert match is None

    def test_empty_candidates(self) -> None:
        match, score = pick_best_match("Creep", "Radiohead", [])
        assert match is None
        assert score == 0.0

    def test_candidate_without_artists(self) -> None:
        candidates = [
            {"id": "x", "uri": "uri:x", "name": "Creep", "artists": []},
        ]
        match, score = pick_best_match("Creep", None, candidates)
        assert match is not None
        assert score >= 60.0


# ═══════════════════════════════════════════════════
#  SpotifyClient._parse_search_response (with fuzzy)
# ═══════════════════════════════════════════════════

class TestParseSearchWithFuzzy:
    def test_high_confidence_match(self) -> None:
        track = Track(
            raw_input="Radiohead - Creep",
            title="Creep",
            artist="Radiohead",
        )
        data = {
            "tracks": {
                "items": [
                    {
                        "id": "abc",
                        "uri": "spotify:track:abc",
                        "name": "Creep",
                        "artists": [{"name": "Radiohead"}],
                    },
                ]
            }
        }
        result = SpotifyClient._parse_search_response(track, data)
        assert result.status == TrackStatus.FOUND
        assert result.confidence >= 0.9

    def test_low_confidence_rejected(self) -> None:
        track = Track(
            raw_input="Something Completely Different",
            title="Something Completely Different",
            artist="Unknown Band",
        )
        data = {
            "tracks": {
                "items": [
                    {
                        "id": "xyz",
                        "uri": "spotify:track:xyz",
                        "name": "Paranoid Android",
                        "artists": [{"name": "Radiohead"}],
                    },
                ]
            }
        }
        result = SpotifyClient._parse_search_response(
            track, data, confidence_threshold=60.0,
        )
        assert result.status == TrackStatus.NOT_FOUND

    def test_remaster_still_matches(self) -> None:
        track = Track(
            raw_input="Queen - Bohemian Rhapsody",
            title="Bohemian Rhapsody",
            artist="Queen",
        )
        data = {
            "tracks": {
                "items": [
                    {
                        "id": "br1",
                        "uri": "spotify:track:br1",
                        "name": "Bohemian Rhapsody (Remastered 2011)",
                        "artists": [{"name": "Queen"}],
                    },
                ]
            }
        }
        result = SpotifyClient._parse_search_response(track, data)
        assert result.status == TrackStatus.FOUND
        assert result.confidence >= 0.8

    def test_picks_best_among_multiple(self) -> None:
        track = Track(
            raw_input="Radiohead - Creep",
            title="Creep",
            artist="Radiohead",
        )
        data = {
            "tracks": {
                "items": [
                    {
                        "id": "wrong",
                        "uri": "spotify:track:wrong",
                        "name": "Creep",
                        "artists": [{"name": "Stone Temple Pilots"}],
                    },
                    {
                        "id": "correct",
                        "uri": "spotify:track:correct",
                        "name": "Creep",
                        "artists": [{"name": "Radiohead"}],
                    },
                ]
            }
        }
        result = SpotifyClient._parse_search_response(track, data)
        assert result.status == TrackStatus.FOUND
        assert result.platform_id == "correct"
