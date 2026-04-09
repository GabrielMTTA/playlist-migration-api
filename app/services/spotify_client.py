"""Spotify concrete implementation of MusicPlatform (Strategy pattern).

Uses the Spotify Web API for:
  - Track search (GET /v1/search)
  - Playlist creation (POST /v1/users/{user_id}/playlists)
  - Adding tracks to playlist (POST /v1/playlists/{id}/tracks)
  - User profile (GET /v1/me)
"""

import logging

import httpx

from app.core.config import settings
from app.core.resilience import (
    BackoffConfig,
    CircuitBreaker,
    request_with_backoff,
)
from app.domain.interfaces import MusicPlatform
from app.domain.models import Track, TrackStatus
from app.services.fuzzy_matcher import pick_best_match

logger = logging.getLogger(__name__)

# Shared circuit breaker for all Spotify API calls
_circuit = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)

# Backoff config tuned for Spotify rate limits
_backoff = BackoffConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    retryable_status_codes=(429, 500, 502, 503, 504),
)


class SpotifyClient(MusicPlatform):
    """Spotify Web API integration."""

    def __init__(self) -> None:
        self._base_url = settings.spotify_api_base_url

    async def search_track(self, track: Track, access_token: str) -> Track:
        """Search Spotify for a track.

        Builds a query from artist + title if available,
        otherwise uses the raw input.
        """
        _circuit.ensure_closed()

        query = self._build_search_query(track)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await request_with_backoff(
                    client,
                    "GET",
                    f"{self._base_url}/search",
                    config=_backoff,
                    params={"q": query, "type": "track", "limit": 5},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.RequestError as exc:
                logger.error("Spotify search network error: %s", exc)
                _circuit.record_failure()
                track.status = TrackStatus.ERROR
                return track

        if response.status_code != 200:
            logger.warning(
                "Spotify search failed (%d) for query: %s",
                response.status_code, query,
            )
            _circuit.record_failure()
            track.status = TrackStatus.ERROR
            return track

        _circuit.record_success()
        return self._parse_search_response(track, response.json())

    async def create_playlist(
        self,
        name: str,
        track_ids: list[str],
        access_token: str,
    ) -> str:
        """Create a Spotify playlist and add tracks to it."""
        _circuit.ensure_closed()

        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            # Step 1: Create empty playlist
            response = await request_with_backoff(
                client,
                "POST",
                f"{self._base_url}/me/playlists",
                config=_backoff,
                headers=headers,
                json={"name": name, "public": False},
            )

            if response.status_code not in (200, 201):
                _circuit.record_failure()
                raise RuntimeError(
                    f"Failed to create playlist ({response.status_code}): "
                    f"{response.text}"
                )

            playlist_data = response.json()
            playlist_id = playlist_data["id"]
            playlist_url = playlist_data["external_urls"]["spotify"]

            # Step 2: Add tracks in batches of 100 (Spotify limit)
            uris = [f"spotify:track:{tid}" for tid in track_ids]
            for i in range(0, len(uris), 100):
                batch = uris[i : i + 100]
                add_response = await request_with_backoff(
                    client,
                    "POST",
                    f"{self._base_url}/playlists/{playlist_id}/tracks",
                    config=_backoff,
                    headers=headers,
                    json={"uris": batch},
                )
                if add_response.status_code not in (200, 201):
                    logger.warning(
                        "Failed to add batch %d to playlist: %s",
                        i // 100, add_response.text,
                    )

        _circuit.record_success()
        return playlist_url

    async def get_user_id(self, access_token: str) -> str:
        """Retrieve the authenticated Spotify user's ID."""
        _circuit.ensure_closed()

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await request_with_backoff(
                client,
                "GET",
                f"{self._base_url}/me",
                config=_backoff,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            _circuit.record_failure()
            raise RuntimeError(
                f"Failed to get user profile ({response.status_code})"
            )

        _circuit.record_success()
        return response.json()["id"]

    # ── Private Helpers ──

    @staticmethod
    def _build_search_query(track: Track) -> str:
        """Build an optimized Spotify search query."""
        if track.artist and track.title:
            return f"artist:{track.artist} track:{track.title}"
        return track.raw_input

    @staticmethod
    def _parse_search_response(
        track: Track,
        data: dict,
        confidence_threshold: float = 60.0,
    ) -> Track:
        """Extract the best match using fuzzy matching against candidates."""
        items = data.get("tracks", {}).get("items", [])

        if not items:
            track.status = TrackStatus.NOT_FOUND
            return track

        best, score = pick_best_match(
            input_title=track.title,
            input_artist=track.artist,
            candidates=items,
            threshold=confidence_threshold,
        )

        if best is None:
            track.status = TrackStatus.NOT_FOUND
            track.confidence = score / 100.0
            return track

        track.platform_id = best["id"]
        track.platform_uri = best["uri"]
        track.status = TrackStatus.FOUND
        track.confidence = score / 100.0

        return track
