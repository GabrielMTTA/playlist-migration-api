"""Phase 4 — Worker Integration, Resilience & SpotifyClient Tests."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.resilience import (
    BackoffConfig,
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    _calculate_delay,
    request_with_backoff,
)
from app.domain.models import Track, TrackStatus
from app.services.spotify_client import SpotifyClient
from app.workers.tasks import _process_playlist_async, _serialize_result
from app.domain.models import ProcessingResult


# ═══════════════════════════════════════════════════
#  Exponential Backoff
# ═══════════════════════════════════════════════════

class TestBackoffConfig:
    def test_default_values(self) -> None:
        c = BackoffConfig()
        assert c.max_retries == 3
        assert c.base_delay == 1.0
        assert 429 in c.retryable_status_codes


class TestCalculateDelay:
    def test_exponential_growth(self) -> None:
        config = BackoffConfig(base_delay=1.0, exponential_base=2.0, max_delay=30.0)
        assert _calculate_delay(0, config) == 1.0
        assert _calculate_delay(1, config) == 2.0
        assert _calculate_delay(2, config) == 4.0
        assert _calculate_delay(3, config) == 8.0

    def test_capped_at_max(self) -> None:
        config = BackoffConfig(base_delay=1.0, exponential_base=2.0, max_delay=5.0)
        assert _calculate_delay(10, config) == 5.0


class TestRequestWithBackoff:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=mock_response)

        result = await request_with_backoff(client, "GET", "https://api.test.com")
        assert result.status_code == 200
        assert client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_429(self) -> None:
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}

        success = MagicMock()
        success.status_code = 200

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[rate_limited, success])

        config = BackoffConfig(max_retries=2, base_delay=0.01)
        result = await request_with_backoff(
            client, "GET", "https://api.test.com", config=config,
        )
        assert result.status_code == 200
        assert client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_respects_retry_after_header(self) -> None:
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "0.01"}

        success = MagicMock()
        success.status_code = 200

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[rate_limited, success])

        config = BackoffConfig(max_retries=1, base_delay=0.001)
        result = await request_with_backoff(
            client, "GET", "https://test.com", config=config,
        )
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_last_response_after_exhaustion(self) -> None:
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.headers = {}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=error_resp)

        config = BackoffConfig(max_retries=1, base_delay=0.01)
        result = await request_with_backoff(
            client, "GET", "https://test.com", config=config,
        )
        assert result.status_code == 500
        assert client.request.call_count == 2


# ═══════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════

class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_ensure_closed_raises_when_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        with pytest.raises(CircuitBreakerOpen):
            cb.ensure_closed()

    def test_success_resets(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        # Should not open after one more failure
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


# ═══════════════════════════════════════════════════
#  SpotifyClient
# ═══════════════════════════════════════════════════

class TestSpotifyClientSearch:
    @pytest.mark.asyncio
    async def test_build_search_query_with_artist(self) -> None:
        query = SpotifyClient._build_search_query(
            Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")
        )
        assert query == "artist:Radiohead track:Creep"

    @pytest.mark.asyncio
    async def test_build_search_query_title_only(self) -> None:
        query = SpotifyClient._build_search_query(
            Track(raw_input="Bohemian Rhapsody", title="Bohemian Rhapsody")
        )
        assert query == "Bohemian Rhapsody"

    @pytest.mark.asyncio
    async def test_parse_search_found(self) -> None:
        track = Track(raw_input="Creep", title="Creep")
        data = {
            "tracks": {
                "items": [
                    {
                        "id": "abc123",
                        "uri": "spotify:track:abc123",
                        "name": "Creep",
                        "artists": [{"name": "Radiohead"}],
                    }
                ]
            }
        }
        result = SpotifyClient._parse_search_response(track, data)
        assert result.status == TrackStatus.FOUND
        assert result.platform_id == "abc123"
        assert result.platform_uri == "spotify:track:abc123"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_parse_search_not_found(self) -> None:
        track = Track(raw_input="Nonexistent", title="Nonexistent")
        data = {"tracks": {"items": []}}
        result = SpotifyClient._parse_search_response(track, data)
        assert result.status == TrackStatus.NOT_FOUND


# ═══════════════════════════════════════════════════
#  Celery Task Logic (async core)
# ═══════════════════════════════════════════════════

class TestProcessPlaylistAsync:
    @pytest.mark.asyncio
    async def test_processes_tracks_and_creates_playlist(self) -> None:
        mock_platform = AsyncMock()

        async def fake_search(track: Track, access_token: str) -> Track:
            track.status = TrackStatus.FOUND
            track.platform_id = f"id_{track.title}"
            return track

        mock_platform.search_track = fake_search
        mock_platform.create_playlist = AsyncMock(
            return_value="https://open.spotify.com/playlist/xyz"
        )

        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        entries = [
            {"raw_input": "Radiohead - Creep", "title": "Creep", "artist": "Radiohead"},
            {"raw_input": "Imagine", "title": "Imagine", "artist": None},
        ]

        with patch(
            "app.workers.tasks.PlatformFactory.create", return_value=mock_platform,
        ):
            result = await _process_playlist_async(
                mock_task, entries, "spotify", "Test Playlist", "token_123",
            )

        assert result["total"] == 2
        assert result["found"] == 2
        assert result["not_found"] == 0
        assert result["playlist_url"] == "https://open.spotify.com/playlist/xyz"
        assert len(result["tracks"]) == 2

    @pytest.mark.asyncio
    async def test_handles_not_found_tracks(self) -> None:
        mock_platform = AsyncMock()

        async def fake_search(track: Track, access_token: str) -> Track:
            track.status = TrackStatus.NOT_FOUND
            return track

        mock_platform.search_track = fake_search
        mock_platform.create_playlist = AsyncMock()

        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        entries = [
            {"raw_input": "Unknown Song", "title": "Unknown Song", "artist": None},
        ]

        with patch(
            "app.workers.tasks.PlatformFactory.create", return_value=mock_platform,
        ):
            result = await _process_playlist_async(
                mock_task, entries, "spotify", "Test", "token",
            )

        assert result["total"] == 1
        assert result["found"] == 0
        assert result["not_found"] == 1
        # No playlist created when no tracks found
        assert result["playlist_url"] is None
        mock_platform.create_playlist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_search_exception(self) -> None:
        mock_platform = AsyncMock()
        mock_platform.search_track = AsyncMock(side_effect=RuntimeError("API down"))
        mock_platform.create_playlist = AsyncMock()

        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        entries = [
            {"raw_input": "Track", "title": "Track", "artist": None},
        ]

        with patch(
            "app.workers.tasks.PlatformFactory.create", return_value=mock_platform,
        ):
            result = await _process_playlist_async(
                mock_task, entries, "spotify", "Test", "token",
            )

        assert result["errors"] == 1
        assert result["found"] == 0

    @pytest.mark.asyncio
    async def test_updates_task_progress(self) -> None:
        mock_platform = AsyncMock()

        async def fake_search(track: Track) -> Track:
            track.status = TrackStatus.FOUND
            track.platform_id = "id"
            return track

        mock_platform.search_track = fake_search
        mock_platform.create_playlist = AsyncMock(return_value="url")

        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        entries = [
            {"raw_input": "A", "title": "A", "artist": None},
            {"raw_input": "B", "title": "B", "artist": None},
            {"raw_input": "C", "title": "C", "artist": None},
        ]

        with patch(
            "app.workers.tasks.PlatformFactory.create", return_value=mock_platform,
        ):
            await _process_playlist_async(
                mock_task, entries, "spotify", "Test", "token",
            )

        # update_state called once per track
        assert mock_task.update_state.call_count == 3


# ═══════════════════════════════════════════════════
#  Serialization
# ═══════════════════════════════════════════════════

class TestSerializeResult:
    def test_serializes_correctly(self) -> None:
        track = Track(
            raw_input="Creep",
            title="Creep",
            platform_id="abc",
            platform_uri="spotify:track:abc",
            status=TrackStatus.FOUND,
            confidence=0.95,
        )
        result = ProcessingResult(
            total=1, found=1, not_found=0, errors=0,
            tracks=[track], playlist_url="https://spotify.com/playlist/xyz",
        )
        serialized = _serialize_result(result)

        assert serialized["total"] == 1
        assert serialized["success_rate"] == 100.0
        assert serialized["playlist_url"] == "https://spotify.com/playlist/xyz"
        assert serialized["tracks"][0]["platform_id"] == "abc"
        assert serialized["tracks"][0]["status"] == "found"


# ═══════════════════════════════════════════════════
#  Task Status Route
# ═══════════════════════════════════════════════════

class TestTaskStatusRoute:
    @patch("app.api.routes.playlist.process_playlist")
    def test_pending_task(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    @patch("app.api.routes.playlist.process_playlist")
    def test_progress_task(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_result = MagicMock()
        mock_result.state = "PROGRESS"
        mock_result.info = {"current": 5, "total": 10, "found": 3}
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["result"]["current"] == 5

    @patch("app.api.routes.playlist.process_playlist")
    def test_completed_task(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = {"total": 10, "found": 8}
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["found"] == 8

    @patch("app.api.routes.playlist.process_playlist")
    def test_failed_task(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.info = Exception("something broke")
        mock_task.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/playlists/tasks/abc-123")
        assert response.status_code == 200
        assert response.json()["status"] == "failed"
