"""Phase 2 — Core Domain, Parsing & Schemas Tests."""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Track, TrackStatus, ProcessingResult
from app.schemas.playlist import PlaylistCreateRequest, PlatformEnum
from app.services.file_parser import parse_file_content, _sanitize_line, _parse_line
from app.services.platform_factory import PlatformFactory
from app.domain.interfaces import MusicPlatform


# ═══════════════════════════════════════════════════
#  Domain Models
# ═══════════════════════════════════════════════════

class TestTrackModel:
    def test_default_status_is_pending(self) -> None:
        t = Track(raw_input="Test", title="Test")
        assert t.status == TrackStatus.PENDING

    def test_artist_optional(self) -> None:
        t = Track(raw_input="Song", title="Song")
        assert t.artist is None

    def test_full_track(self) -> None:
        t = Track(
            raw_input="Radiohead - Creep",
            title="Creep",
            artist="Radiohead",
            platform_id="abc123",
            status=TrackStatus.FOUND,
            confidence=0.95,
        )
        assert t.artist == "Radiohead"
        assert t.confidence == 0.95


class TestProcessingResult:
    def test_success_rate_calculation(self) -> None:
        r = ProcessingResult(total=10, found=7)
        assert r.success_rate == 70.0

    def test_success_rate_zero_total(self) -> None:
        r = ProcessingResult(total=0, found=0)
        assert r.success_rate == 0.0

    def test_success_rate_full(self) -> None:
        r = ProcessingResult(total=5, found=5)
        assert r.success_rate == 100.0


# ═══════════════════════════════════════════════════
#  File Parser
# ═══════════════════════════════════════════════════

class TestSanitizeLine:
    def test_strips_whitespace(self) -> None:
        assert _sanitize_line("  hello  ") == "hello"

    def test_removes_null_bytes(self) -> None:
        assert _sanitize_line("hello\x00world") == "helloworld"

    def test_removes_control_chars(self) -> None:
        assert _sanitize_line("abc\x07def") == "abcdef"

    def test_truncates_long_lines(self) -> None:
        long_line = "a" * 500
        assert len(_sanitize_line(long_line)) == 300


class TestParseLine:
    def test_artist_title_format(self) -> None:
        track = _parse_line("Radiohead - Creep")
        assert track is not None
        assert track.artist == "Radiohead"
        assert track.title == "Creep"

    def test_title_only_format(self) -> None:
        track = _parse_line("Bohemian Rhapsody")
        assert track is not None
        assert track.title == "Bohemian Rhapsody"
        assert track.artist is None

    def test_empty_line_returns_none(self) -> None:
        assert _parse_line("") is None
        assert _parse_line("   ") is None

    def test_comment_line_returns_none(self) -> None:
        assert _parse_line("# This is a comment") is None

    def test_multiple_dashes(self) -> None:
        track = _parse_line("AC/DC - Back in Black - Remastered")
        assert track is not None
        assert track.artist == "AC/DC"
        assert track.title == "Back in Black - Remastered"

    def test_dash_without_spaces_is_title(self) -> None:
        track = _parse_line("Run-DMC")
        assert track is not None
        assert track.title == "Run-DMC"
        assert track.artist is None


class TestParseFileContent:
    def test_parses_multiple_lines(self) -> None:
        content = "Radiohead - Creep\nNirvana - Smells Like Teen Spirit\nImagine"
        tracks = parse_file_content(content)
        assert len(tracks) == 3

    def test_skips_empty_and_comment_lines(self) -> None:
        content = "# My Playlist\n\nRadiohead - Creep\n\n# End"
        tracks = parse_file_content(content)
        assert len(tracks) == 1

    def test_raises_on_empty_content(self) -> None:
        with pytest.raises(ValueError, match="No valid tracks"):
            parse_file_content("")

    def test_raises_on_only_comments(self) -> None:
        with pytest.raises(ValueError, match="No valid tracks"):
            parse_file_content("# comment\n# another")

    def test_enforces_max_lines(self) -> None:
        content = "\n".join(f"Track {i}" for i in range(600))
        tracks = parse_file_content(content)
        assert len(tracks) == 500

    def test_windows_line_endings(self) -> None:
        content = "Track A\r\nTrack B\r\n"
        tracks = parse_file_content(content)
        assert len(tracks) == 2


# ═══════════════════════════════════════════════════
#  Pydantic Schemas
# ═══════════════════════════════════════════════════

class TestPlaylistCreateRequest:
    def test_valid_request(self) -> None:
        req = PlaylistCreateRequest(
            platform=PlatformEnum.SPOTIFY,
            track_names=["Radiohead - Creep", "Imagine"],
        )
        assert len(req.track_names) == 2

    def test_sanitizes_whitespace(self) -> None:
        req = PlaylistCreateRequest(
            platform=PlatformEnum.SPOTIFY,
            track_names=["  Creep  ", "  Imagine  "],
        )
        assert req.track_names == ["Creep", "Imagine"]

    def test_filters_empty_strings(self) -> None:
        req = PlaylistCreateRequest(
            platform=PlatformEnum.SPOTIFY,
            track_names=["Creep", "", "   "],
        )
        assert req.track_names == ["Creep"]

    def test_rejects_all_empty(self) -> None:
        with pytest.raises(ValueError):
            PlaylistCreateRequest(
                platform=PlatformEnum.SPOTIFY,
                track_names=["", "   "],
            )

    def test_truncates_long_names(self) -> None:
        long_name = "a" * 500
        req = PlaylistCreateRequest(
            platform=PlatformEnum.SPOTIFY,
            track_names=[long_name],
        )
        assert len(req.track_names[0]) == 300

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(ValueError):
            PlaylistCreateRequest(
                platform=PlatformEnum.SPOTIFY,
                track_names=[],
            )


# ═══════════════════════════════════════════════════
#  Platform Factory
# ═══════════════════════════════════════════════════

class TestPlatformFactory:
    def test_create_returns_registered_platform(self) -> None:
        # Spotify is registered at app startup (app.main imports)
        instance = PlatformFactory.create(PlatformEnum.SPOTIFY)
        assert instance is not None
        assert "spotify" in PlatformFactory.available_platforms()

    def test_register_custom_and_create(self) -> None:
        class FakePlatform(MusicPlatform):
            async def search_track(self, track: Track, access_token: str) -> Track:
                return track

            async def create_playlist(
                self, name: str, track_ids: list[str], access_token: str
            ) -> str:
                return "url"

            async def get_user_id(self, access_token: str) -> str:
                return "user"

        # Save original registry to restore later
        original = PlatformFactory._registry.copy()
        PlatformFactory.register(PlatformEnum.SPOTIFY, FakePlatform)
        instance = PlatformFactory.create(PlatformEnum.SPOTIFY)
        assert isinstance(instance, FakePlatform)

        # Restore
        PlatformFactory._registry = original


# ═══════════════════════════════════════════════════
#  Upload Endpoint
# ═══════════════════════════════════════════════════

class TestUploadEndpoint:
    AUTH_HEADER = {"Authorization": "Bearer test_token"}

    @patch("app.api.routes.playlist.process_playlist")
    def test_valid_txt_upload(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_task.delay.return_value = MagicMock(id="fake-task-id")
        content = b"Radiohead - Creep\nNirvana - Smells Like Teen Spirit"
        response = client.post(
            "/api/v1/playlists/upload",
            files={"file": ("playlist.txt", io.BytesIO(content), "text/plain")},
            data={"platform": "spotify", "playlist_name": "My Playlist"},
            headers=self.AUTH_HEADER,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["task_id"] == "fake-task-id"

    def test_rejects_non_txt_file(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/playlists/upload",
            files={"file": ("music.csv", io.BytesIO(b"data"), "text/csv")},
            headers=self.AUTH_HEADER,
        )
        assert response.status_code == 415

    def test_rejects_empty_file(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/playlists/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            headers=self.AUTH_HEADER,
        )
        assert response.status_code == 422

    @patch("app.api.routes.playlist.process_playlist")
    def test_json_endpoint(self, mock_task: MagicMock, client: TestClient) -> None:
        mock_task.delay.return_value = MagicMock(id="json-task-id")
        response = client.post(
            "/api/v1/playlists/",
            json={
                "platform": "spotify",
                "track_names": ["Creep", "Imagine"],
                "playlist_name": "Test",
            },
            headers=self.AUTH_HEADER,
        )
        assert response.status_code == 202
        assert response.json()["task_id"] == "json-task-id"

    def test_upload_requires_auth(self, client: TestClient) -> None:
        content = b"Track 1"
        response = client.post(
            "/api/v1/playlists/upload",
            files={"file": ("test.txt", io.BytesIO(content), "text/plain")},
        )
        assert response.status_code == 422  # missing header
