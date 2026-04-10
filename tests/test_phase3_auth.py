"""Phase 3 — Auth Layer (OAuth 2.0) Tests."""

from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import require_access_token
from app.services.oauth import (
    GoogleOAuthProvider,
    OAuthError,
    OAuthProviderFactory,
    SpotifyOAuthProvider,
    TokenResponse,
)


# ═══════════════════════════════════════════════════
#  SpotifyOAuthProvider — Unit Tests
# ═══════════════════════════════════════════════════

class TestBuildAuthUrl:
    def test_returns_url_and_state(self) -> None:
        provider = SpotifyOAuthProvider()
        url, state = provider.build_auth_url()
        assert "https://accounts.spotify.com/authorize" in url
        assert "client_id=" in url
        assert "response_type=code" in url
        assert "state=" in url
        assert len(state) > 20

    def test_state_is_unique_per_call(self) -> None:
        provider = SpotifyOAuthProvider()
        _, state1 = provider.build_auth_url()
        _, state2 = provider.build_auth_url()
        assert state1 != state2

    def test_url_contains_scopes(self) -> None:
        provider = SpotifyOAuthProvider()
        url, _ = provider.build_auth_url()
        assert "playlist-modify" in url


class TestBuildAuthHeader:
    def test_basic_auth_encoding(self) -> None:
        provider = SpotifyOAuthProvider()
        provider._client_id = "test_id"
        provider._client_secret = "test_secret"
        header = provider._build_auth_header()
        expected = b64encode(b"test_id:test_secret").decode()
        assert header == f"Basic {expected}"


class TestExchangeCode:
    @pytest.mark.asyncio
    async def test_successful_exchange(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with patch("app.services.oauth.spotify_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = SpotifyOAuthProvider()
            token = await provider.exchange_code("auth_code_xyz")

        assert token.access_token == "access_123"
        assert token.refresh_token == "refresh_456"
        assert token.expires_in == 3600
        assert token.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_exchange_failure_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("app.services.oauth.spotify_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = SpotifyOAuthProvider()
            with pytest.raises(OAuthError, match="400"):
                await provider.exchange_code("bad_code")


class TestRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_successful_refresh(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_789",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with patch("app.services.oauth.spotify_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = SpotifyOAuthProvider()
            token = await provider.refresh_access_token("old_refresh_token")

        assert token.access_token == "new_access_789"
        # When Spotify doesn't return a new refresh token, keep the old one
        assert token.refresh_token == "old_refresh_token"

    @pytest.mark.asyncio
    async def test_refresh_with_rotated_token(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "rotated_refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with patch("app.services.oauth.spotify_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = SpotifyOAuthProvider()
            token = await provider.refresh_access_token("old_refresh")

        assert token.refresh_token == "rotated_refresh"


# ═══════════════════════════════════════════════════
#  Auth Routes — Integration Tests (parametrized paths)
# ═══════════════════════════════════════════════════

class TestLoginRoute:
    def test_login_returns_auth_url(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/spotify/login")
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state" in data
        assert "accounts.spotify.com" in data["auth_url"]

    def test_login_invalid_platform_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/invalid_platform/login")
        assert response.status_code == 422


class TestCallbackRoute:
    def test_callback_success(self, client: TestClient) -> None:
        mock_token = TokenResponse(
            access_token="acc_123",
            refresh_token="ref_456",
            expires_in=3600,
            token_type="Bearer",
        )
        with patch.object(
            SpotifyOAuthProvider, "exchange_code", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.get(
                "/api/v1/auth/spotify/callback",
                params={"code": "valid_code", "state": "valid_state"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "acc_123"
        assert data["refresh_token"] == "ref_456"

    def test_callback_auth_error(self, client: TestClient) -> None:
        with patch.object(
            SpotifyOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            side_effect=OAuthError("invalid_grant"),
        ):
            response = client.get(
                "/api/v1/auth/spotify/callback",
                params={"code": "bad_code", "state": "some_state"},
            )
        assert response.status_code == 502

    def test_callback_missing_code(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/spotify/callback", params={"state": "s"})
        assert response.status_code == 422


class TestRefreshRoute:
    def test_refresh_success(self, client: TestClient) -> None:
        mock_token = TokenResponse(
            access_token="new_acc",
            refresh_token="same_ref",
            expires_in=3600,
            token_type="Bearer",
        )
        with patch.object(
            SpotifyOAuthProvider, "refresh_access_token", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.post(
                "/api/v1/auth/spotify/refresh",
                json={"refresh_token": "my_refresh_token"},
            )
        assert response.status_code == 200
        assert response.json()["access_token"] == "new_acc"

    def test_refresh_missing_body(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/spotify/refresh", json={})
        assert response.status_code == 422


# ═══════════════════════════════════════════════════
#  OAuthProviderFactory — Unit Tests
# ═══════════════════════════════════════════════════

class TestOAuthProviderFactory:
    def test_create_returns_spotify_provider(self) -> None:
        from app.schemas.playlist import PlatformEnum
        provider = OAuthProviderFactory.create(PlatformEnum.SPOTIFY)
        assert isinstance(provider, SpotifyOAuthProvider)

    def test_create_unregistered_raises(self) -> None:
        from app.schemas.playlist import PlatformEnum
        # Temporarily clear registry to test error path
        original = OAuthProviderFactory._registry.copy()
        OAuthProviderFactory._registry.clear()
        try:
            with pytest.raises(ValueError, match="No OAuth provider"):
                OAuthProviderFactory.create(PlatformEnum.SPOTIFY)
        finally:
            OAuthProviderFactory._registry = original

    def test_available_platforms(self) -> None:
        platforms = OAuthProviderFactory.available_platforms()
        assert "spotify" in platforms
        assert "youtube_music" in platforms


# ═══════════════════════════════════════════════════
#  Dependency — require_access_token
# ═══════════════════════════════════════════════════

class TestRequireAccessToken:
    @pytest.mark.asyncio
    async def test_valid_bearer_token(self) -> None:
        token = await require_access_token("Bearer my_token_123")
        assert token == "my_token_123"

    @pytest.mark.asyncio
    async def test_rejects_non_bearer(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_access_token("Basic abc123")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_empty_token(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await require_access_token("Bearer ")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_strips_whitespace(self) -> None:
        token = await require_access_token("Bearer   my_token   ")
        assert token == "my_token"


# ═══════════════════════════════════════════════════
#  GoogleOAuthProvider — Unit Tests
# ═══════════════════════════════════════════════════

class TestGoogleBuildAuthUrl:
    def test_returns_url_and_state(self) -> None:
        provider = GoogleOAuthProvider()
        url, state = provider.build_auth_url()
        assert "accounts.google.com" in url
        assert "client_id=" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert len(state) > 20

    def test_state_is_unique_per_call(self) -> None:
        provider = GoogleOAuthProvider()
        _, state1 = provider.build_auth_url()
        _, state2 = provider.build_auth_url()
        assert state1 != state2

    def test_url_contains_youtube_scope(self) -> None:
        provider = GoogleOAuthProvider()
        url, _ = provider.build_auth_url()
        assert "youtube" in url


class TestGoogleExchangeCode:
    @pytest.mark.asyncio
    async def test_successful_exchange(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.google_access",
            "refresh_token": "1//google_refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with patch("app.services.oauth.google_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = GoogleOAuthProvider()
            token = await provider.exchange_code("google_auth_code")

        assert token.access_token == "ya29.google_access"
        assert token.refresh_token == "1//google_refresh"
        assert token.expires_in == 3600

    @pytest.mark.asyncio
    async def test_exchange_failure_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("app.services.oauth.google_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = GoogleOAuthProvider()
            with pytest.raises(OAuthError, match="400"):
                await provider.exchange_code("bad_code")


class TestGoogleRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_successful_refresh(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new_access",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with patch("app.services.oauth.google_provider.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            provider = GoogleOAuthProvider()
            token = await provider.refresh_access_token("1//old_refresh")

        assert token.access_token == "ya29.new_access"
        assert token.refresh_token == "1//old_refresh"


# ═══════════════════════════════════════════════════
#  YouTube Music Auth Routes — Integration Tests
# ═══════════════════════════════════════════════════

class TestYouTubeMusicLoginRoute:
    def test_login_returns_google_auth_url(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/youtube_music/login")
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state" in data
        assert "accounts.google.com" in data["auth_url"]


class TestYouTubeMusicCallbackRoute:
    def test_callback_success(self, client: TestClient) -> None:
        mock_token = TokenResponse(
            access_token="ya29.google",
            refresh_token="1//refresh",
            expires_in=3600,
            token_type="Bearer",
        )
        with patch.object(
            GoogleOAuthProvider, "exchange_code", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.get(
                "/api/v1/auth/youtube_music/callback",
                params={"code": "valid_code", "state": "valid_state"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "ya29.google"
        assert data["refresh_token"] == "1//refresh"

    def test_callback_auth_error(self, client: TestClient) -> None:
        with patch.object(
            GoogleOAuthProvider,
            "exchange_code",
            new_callable=AsyncMock,
            side_effect=OAuthError("invalid_grant"),
        ):
            response = client.get(
                "/api/v1/auth/youtube_music/callback",
                params={"code": "bad_code", "state": "some_state"},
            )
        assert response.status_code == 502


class TestYouTubeMusicRefreshRoute:
    def test_refresh_success(self, client: TestClient) -> None:
        mock_token = TokenResponse(
            access_token="ya29.refreshed",
            refresh_token="1//same",
            expires_in=3600,
            token_type="Bearer",
        )
        with patch.object(
            GoogleOAuthProvider, "refresh_access_token", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.post(
                "/api/v1/auth/youtube_music/refresh",
                json={"refresh_token": "1//my_refresh"},
            )
        assert response.status_code == 200
        assert response.json()["access_token"] == "ya29.refreshed"
