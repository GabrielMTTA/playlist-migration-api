"""YouTube Music concrete implementation of MusicPlatform (Strategy pattern).

Uses the YouTube Data API v3 for:
  - Track search (GET /youtube/v3/search) — 100 units per call
  - User channel (GET /youtube/v3/channels?mine=true) — 1 unit
  - Playlist creation (POST /youtube/v3/playlists) — 50 units
  - Add video to playlist (POST /youtube/v3/playlistItems) — 50 units each

CRITICAL: YouTube quota is 10,000 units/day. A 19-track playlist costs
~1,900 units (search) + 50 (create) + 950 (add 19 videos) = ~2,900 units.
Redis cache is mandatory to avoid waste.
"""

import logging
import re

import httpx

from app.core.config import settings
from app.core.resilience import (
    BackoffConfig,
    CircuitBreaker,
    request_with_backoff,
)
from app.domain.interfaces import MusicPlatform
from app.domain.models import MatchCandidate, Track, TrackStatus
from app.services.fuzzy_matcher import pick_best_match
from app.services.search_cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_circuit = CircuitBreaker(failure_threshold=5, recovery_timeout=120.0)

_backoff = BackoffConfig(
    max_retries=2,
    base_delay=2.0,
    max_delay=30.0,
    retryable_status_codes=(429, 500, 502, 503),
)

# Patterns to clean up YouTube channel names
_VEVO_SUFFIX = re.compile(r"VEVO$", re.IGNORECASE)
_TOPIC_SUFFIX = re.compile(r"\s*-\s*Topic$", re.IGNORECASE)


class YouTubeMusicClient(MusicPlatform):
    """YouTube Music integration via YouTube Data API v3."""

    def __init__(self) -> None:
        self._base_url = settings.youtube_api_base_url

    async def search_track(self, track: Track, access_token: str) -> Track:
        """Search YouTube for a music video matching the track.

        Retries with artist/title swapped when the first attempt returns
        NOT_FOUND — handles "Song - Artist" input order.
        """
        _circuit.ensure_closed()

        result = await self._search_once(track, access_token)

        # Retry with swapped order (Song - Artist → Artist - Song)
        if (
            result.status == TrackStatus.NOT_FOUND
            and track.artist
            and track.title
        ):
            swapped = Track(
                raw_input=track.raw_input,
                title=track.artist,
                artist=track.title,
            )
            swapped_result = await self._search_once(swapped, access_token)
            if swapped_result.status == TrackStatus.FOUND:
                logger.debug(
                    "Found track with swapped order: %s", track.raw_input
                )
                return swapped_result

        return result

    async def _search_once(self, track: Track, access_token: str) -> Track:
        """Single YouTube search attempt for a track (with cache)."""
        query = self._build_search_query(track)

        # -- Check cache first (saves 100 quota units per hit) --
        cached = cache_get("youtube_music", query)
        if cached is not None:
            logger.debug("Cache hit for YouTube search: %s", query)
            return self._pick_from_candidates(track, cached)

        # -- Cache miss: call YouTube API --
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await request_with_backoff(
                    client,
                    "GET",
                    f"{self._base_url}/search",
                    config=_backoff,
                    params={
                        "part": "snippet",
                        "q": query,
                        "type": "video",
                        "videoCategoryId": "10",  # Music
                        "maxResults": 5,
                    },
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.RequestError as exc:
                logger.error("YouTube search network error: %s", exc)
                _circuit.record_failure()
                track.status = TrackStatus.ERROR
                return track

        if response.status_code != 200:
            logger.warning(
                "YouTube search failed (%d) for query: %s",
                response.status_code, query,
            )
            _circuit.record_failure()
            track.status = TrackStatus.ERROR
            return track

        _circuit.record_success()

        candidates = self._parse_search_items(response.json())

        # -- Store in cache --
        if candidates:
            cache_set("youtube_music", query, candidates)

        return self._pick_from_candidates(track, candidates)

    async def create_playlist(
        self,
        name: str,
        track_ids: list[str],
        access_token: str,
    ) -> str:
        """Create a YouTube playlist and add videos to it.

        Quota cost: 50 (create) + 50 per video = 50 + 50N units.
        YouTube has no batch insert — each video is a separate API call.
        """
        _circuit.ensure_closed()

        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            # Step 1: Create empty playlist (50 units)
            response = await request_with_backoff(
                client,
                "POST",
                f"{self._base_url}/playlists",
                config=_backoff,
                params={"part": "snippet,status"},
                headers=headers,
                json={
                    "snippet": {
                        "title": name,
                        "description": "Created by Playlist Migration API",
                    },
                    "status": {"privacyStatus": "private"},
                },
            )

            if response.status_code not in (200, 201):
                _circuit.record_failure()
                raise RuntimeError(
                    f"Failed to create YouTube playlist ({response.status_code}): "
                    f"{response.text}"
                )

            playlist_data = response.json()
            playlist_id = playlist_data["id"]
            playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"

            # Step 2: Add videos one by one (50 units each)
            for video_id in track_ids:
                add_response = await request_with_backoff(
                    client,
                    "POST",
                    f"{self._base_url}/playlistItems",
                    config=_backoff,
                    params={"part": "snippet"},
                    headers=headers,
                    json={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        },
                    },
                )
                if add_response.status_code not in (200, 201):
                    logger.warning(
                        "Failed to add video %s to playlist: %s",
                        video_id, add_response.text,
                    )

        _circuit.record_success()
        return playlist_url

    async def get_user_id(self, access_token: str) -> str:
        """Retrieve the authenticated user's YouTube channel ID."""
        _circuit.ensure_closed()

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await request_with_backoff(
                client,
                "GET",
                f"{self._base_url}/channels",
                config=_backoff,
                params={"part": "id", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            _circuit.record_failure()
            raise RuntimeError(
                f"Failed to get YouTube channel ({response.status_code})"
            )

        _circuit.record_success()
        items = response.json().get("items", [])
        if not items:
            raise RuntimeError("No YouTube channel found for this account")
        return items[0]["id"]

    # -- Private Helpers --

    @staticmethod
    def _build_search_query(track: Track) -> str:
        """Build a YouTube search query from track info."""
        if track.artist and track.title:
            return f"{track.artist} {track.title}"
        return track.raw_input

    @staticmethod
    def _clean_channel_name(channel: str) -> str:
        """Remove VEVO / '- Topic' suffixes from channel names."""
        cleaned = _VEVO_SUFFIX.sub("", channel).strip()
        cleaned = _TOPIC_SUFFIX.sub("", cleaned).strip()
        return cleaned

    @classmethod
    def _parse_search_items(cls, data: dict) -> list[MatchCandidate]:
        """Convert YouTube API response items to MatchCandidate list."""
        items = data.get("items", [])
        candidates = []

        for item in items:
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})

            if not video_id:
                continue

            candidates.append(
                MatchCandidate(
                    id=video_id,
                    uri=f"https://music.youtube.com/watch?v={video_id}",
                    title=snippet.get("title", ""),
                    artist=cls._clean_channel_name(
                        snippet.get("channelTitle", "")
                    ),
                )
            )

        return candidates

    @staticmethod
    def _pick_from_candidates(
        track: Track,
        candidates: list[MatchCandidate],
        confidence_threshold: float = 60.0,
    ) -> Track:
        """Run fuzzy matching on candidates and update track status."""
        if not candidates:
            track.status = TrackStatus.NOT_FOUND
            return track

        best, score = pick_best_match(
            input_title=track.title,
            input_artist=track.artist,
            candidates=candidates,
            threshold=confidence_threshold,
        )

        if best is None:
            track.status = TrackStatus.NOT_FOUND
            track.confidence = score / 100.0
            return track

        track.platform_id = best.id
        track.platform_uri = best.uri
        track.status = TrackStatus.FOUND
        track.confidence = score / 100.0

        return track
