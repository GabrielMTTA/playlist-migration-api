"""Phase 10 — YouTube Music Client & Search Cache Tests."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models import MatchCandidate, Track, TrackStatus
from app.services.youtube_music_client import YouTubeMusicClient


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — Query Building
# ═══════════════════════════════════════════════════

class TestBuildSearchQuery:
    def test_artist_and_title(self) -> None:
        track = Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")
        assert YouTubeMusicClient._build_search_query(track) == "Radiohead Creep"

    def test_title_only(self) -> None:
        track = Track(raw_input="Creep", title="Creep", artist=None)
        assert YouTubeMusicClient._build_search_query(track) == "Creep"


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — Channel Name Cleaning
# ═══════════════════════════════════════════════════

class TestCleanChannelName:
    def test_removes_vevo(self) -> None:
        assert YouTubeMusicClient._clean_channel_name("RadioheadVEVO") == "Radiohead"

    def test_removes_topic(self) -> None:
        assert YouTubeMusicClient._clean_channel_name("Radiohead - Topic") == "Radiohead"

    def test_plain_name_unchanged(self) -> None:
        assert YouTubeMusicClient._clean_channel_name("Radiohead") == "Radiohead"

    def test_empty_string(self) -> None:
        assert YouTubeMusicClient._clean_channel_name("") == ""


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — Response Parsing
# ═══════════════════════════════════════════════════

class TestParseSearchItems:
    YOUTUBE_RESPONSE = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "Radiohead - Creep (Official Video)",
                    "channelTitle": "RadioheadVEVO",
                },
            },
            {
                "id": {"videoId": "def456"},
                "snippet": {
                    "title": "Creep - Radiohead (Lyrics)",
                    "channelTitle": "LyricsFinder",
                },
            },
        ]
    }

    def test_parses_candidates(self) -> None:
        candidates = YouTubeMusicClient._parse_search_items(self.YOUTUBE_RESPONSE)
        assert len(candidates) == 2

    def test_extracts_video_id(self) -> None:
        candidates = YouTubeMusicClient._parse_search_items(self.YOUTUBE_RESPONSE)
        assert candidates[0].id == "abc123"

    def test_builds_youtube_music_uri(self) -> None:
        candidates = YouTubeMusicClient._parse_search_items(self.YOUTUBE_RESPONSE)
        assert candidates[0].uri == "https://music.youtube.com/watch?v=abc123"

    def test_cleans_channel_name(self) -> None:
        candidates = YouTubeMusicClient._parse_search_items(self.YOUTUBE_RESPONSE)
        assert candidates[0].artist == "Radiohead"

    def test_empty_response(self) -> None:
        candidates = YouTubeMusicClient._parse_search_items({"items": []})
        assert candidates == []

    def test_skips_items_without_video_id(self) -> None:
        data = {
            "items": [
                {"id": {}, "snippet": {"title": "X", "channelTitle": "Y"}},
                {"id": {"videoId": "v1"}, "snippet": {"title": "X", "channelTitle": "Y"}},
            ]
        }
        candidates = YouTubeMusicClient._parse_search_items(data)
        assert len(candidates) == 1


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — Fuzzy Match Integration
# ═══════════════════════════════════════════════════

class TestPickFromCandidates:
    def test_finds_matching_track(self) -> None:
        track = Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")
        candidates = [
            MatchCandidate(
                id="abc",
                uri="https://music.youtube.com/watch?v=abc",
                title="Radiohead - Creep (Official Video)",
                artist="Radiohead",
            ),
        ]
        result = YouTubeMusicClient._pick_from_candidates(track, candidates)
        assert result.status == TrackStatus.FOUND
        assert result.platform_id == "abc"
        assert result.confidence >= 0.6

    def test_returns_not_found_on_empty(self) -> None:
        track = Track(raw_input="Unknown - Song", title="Song", artist="Unknown")
        result = YouTubeMusicClient._pick_from_candidates(track, [])
        assert result.status == TrackStatus.NOT_FOUND

    def test_returns_not_found_below_threshold(self) -> None:
        track = Track(
            raw_input="Something Completely Different",
            title="Something Completely Different",
            artist="Unknown Band",
        )
        candidates = [
            MatchCandidate(
                id="xyz",
                uri="https://music.youtube.com/watch?v=xyz",
                title="Never Gonna Give You Up",
                artist="Rick Astley",
            ),
        ]
        result = YouTubeMusicClient._pick_from_candidates(track, candidates)
        assert result.status == TrackStatus.NOT_FOUND


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — search_track (mocked HTTP)
# ═══════════════════════════════════════════════════

class TestSearchTrack:
    @pytest.mark.asyncio
    async def test_search_with_cache_miss(self) -> None:
        track = Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "id": {"videoId": "yt_abc"},
                    "snippet": {
                        "title": "Radiohead - Creep",
                        "channelTitle": "RadioheadVEVO",
                    },
                },
            ]
        }

        with patch("app.services.youtube_music_client.cache_get", return_value=None), \
             patch("app.services.youtube_music_client.cache_set") as mock_cache_set, \
             patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=mock_response):
            client = YouTubeMusicClient()
            result = await client.search_track(track, "fake_token")

        assert result.status == TrackStatus.FOUND
        assert result.platform_id == "yt_abc"
        assert "music.youtube.com" in result.platform_uri
        mock_cache_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_cache_hit(self) -> None:
        track = Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")
        cached = [
            MatchCandidate(
                id="cached_id",
                uri="https://music.youtube.com/watch?v=cached_id",
                title="Radiohead - Creep",
                artist="Radiohead",
            ),
        ]

        with patch("app.services.youtube_music_client.cache_get", return_value=cached):
            client = YouTubeMusicClient()
            result = await client.search_track(track, "fake_token")

        assert result.status == TrackStatus.FOUND
        assert result.platform_id == "cached_id"

    @pytest.mark.asyncio
    async def test_search_api_error(self) -> None:
        track = Track(raw_input="Radiohead - Creep", title="Creep", artist="Radiohead")

        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("app.services.youtube_music_client.cache_get", return_value=None), \
             patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=mock_response):
            client = YouTubeMusicClient()
            result = await client.search_track(track, "fake_token")

        assert result.status == TrackStatus.ERROR


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — get_user_id (mocked HTTP)
# ═══════════════════════════════════════════════════

class TestGetUserId:
    @pytest.mark.asyncio
    async def test_returns_channel_id(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [{"id": "UC_channel_123"}]
        }

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=mock_response):
            client = YouTubeMusicClient()
            user_id = await client.get_user_id("fake_token")

        assert user_id == "UC_channel_123"

    @pytest.mark.asyncio
    async def test_no_channel_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": []}

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=mock_response):
            client = YouTubeMusicClient()
            with pytest.raises(RuntimeError, match="No YouTube channel"):
                await client.get_user_id("fake_token")


# ═══════════════════════════════════════════════════
#  SearchCache — Unit Tests (mocked Redis)
# ═══════════════════════════════════════════════════

class TestSearchCache:
    def test_cache_miss_returns_none(self) -> None:
        from app.services.search_cache import cache_get
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            result = cache_get("youtube_music", "radiohead creep")
        assert result is None

    def test_cache_hit_returns_candidates(self) -> None:
        from app.services.search_cache import cache_get
        cached_data = json.dumps([
            {"id": "v1", "uri": "uri:v1", "title": "Creep", "artist": "Radiohead"},
        ])
        mock_redis = MagicMock()
        mock_redis.get.return_value = cached_data
        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            result = cache_get("youtube_music", "radiohead creep")
        assert result is not None
        assert len(result) == 1
        assert result[0].id == "v1"
        assert isinstance(result[0], MatchCandidate)

    def test_cache_set_stores_data(self) -> None:
        from app.services.search_cache import cache_set
        mock_redis = MagicMock()
        candidates = [
            MatchCandidate(id="v1", uri="uri:v1", title="Creep", artist="Radiohead"),
        ]
        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            cache_set("youtube_music", "radiohead creep", candidates, ttl=3600)
        mock_redis.setex.assert_called_once()
        key, ttl, data = mock_redis.setex.call_args[0]
        assert "youtube_music" in key
        assert ttl == 3600
        parsed = json.loads(data)
        assert parsed[0]["id"] == "v1"

    def test_cache_redis_error_returns_none(self) -> None:
        import redis
        from app.services.search_cache import cache_get
        mock_redis = MagicMock()
        mock_redis.get.side_effect = redis.RedisError("connection refused")
        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            result = cache_get("youtube_music", "test query")
        assert result is None

    def test_cache_set_redis_error_silent(self) -> None:
        import redis
        from app.services.search_cache import cache_set
        mock_redis = MagicMock()
        mock_redis.setex.side_effect = redis.RedisError("connection refused")
        candidates = [
            MatchCandidate(id="v1", uri="uri:v1", title="X", artist="Y"),
        ]
        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            cache_set("youtube_music", "test", candidates)
        # Should not raise — just log warning


# ═══════════════════════════════════════════════════
#  PlatformFactory — YouTube Music Registration
# ═══════════════════════════════════════════════════

class TestYouTubeMusicFactoryRegistration:
    def test_youtube_music_is_registered(self) -> None:
        from app.schemas.playlist import PlatformEnum
        from app.services.platform_factory import PlatformFactory
        client = PlatformFactory.create(PlatformEnum.YOUTUBE_MUSIC)
        assert isinstance(client, YouTubeMusicClient)

    def test_available_platforms_includes_youtube(self) -> None:
        from app.services.platform_factory import PlatformFactory
        platforms = PlatformFactory.available_platforms()
        assert "youtube_music" in platforms


# ═══════════════════════════════════════════════════
#  YouTubeMusicClient — create_playlist (mocked HTTP)
# ═══════════════════════════════════════════════════

class TestCreatePlaylist:
    @pytest.mark.asyncio
    async def test_creates_playlist_and_adds_videos(self) -> None:
        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {"id": "PL_abc123"}

        add_response = MagicMock()
        add_response.status_code = 200

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return create_response
            return add_response

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, side_effect=mock_request):
            client = YouTubeMusicClient()
            url = await client.create_playlist("My Playlist", ["vid1", "vid2"], "fake_token")

        assert "music.youtube.com/playlist" in url
        assert "PL_abc123" in url
        assert call_count == 3  # 1 create + 2 add

    @pytest.mark.asyncio
    async def test_create_playlist_failure_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "quotaExceeded"

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=mock_response):
            client = YouTubeMusicClient()
            with pytest.raises(RuntimeError, match="Failed to create YouTube playlist"):
                await client.create_playlist("Test", ["vid1"], "fake_token")

    @pytest.mark.asyncio
    async def test_add_video_failure_logged_not_raised(self) -> None:
        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {"id": "PL_xyz"}

        add_fail = MagicMock()
        add_fail.status_code = 404
        add_fail.text = "videoNotFound"

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return create_response
            return add_fail

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, side_effect=mock_request):
            client = YouTubeMusicClient()
            url = await client.create_playlist("Test", ["bad_vid"], "fake_token")

        # Playlist is still created, even if adding a video fails
        assert "PL_xyz" in url

    @pytest.mark.asyncio
    async def test_empty_track_ids_creates_empty_playlist(self) -> None:
        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {"id": "PL_empty"}

        with patch("app.services.youtube_music_client.request_with_backoff", new_callable=AsyncMock, return_value=create_response):
            client = YouTubeMusicClient()
            url = await client.create_playlist("Empty", [], "fake_token")

        assert "PL_empty" in url
