"""Phase 3 — Auth Layer (Spotify OAuth 2.0) Tests."""

from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import require_access_token
from app.services.spotify_auth import (
    SpotifyAuthError,
    SpotifyAuthService,
    TokenResponse,
)


# ═══════════════════════════════════════════════════
#  SpotifyAuthService — Unit Tests
# ═══════════════════════════════════════════════════

class TestBuildAuthUrl:
    def test_returns_url_and_state(self) -> None:
        service = SpotifyAuthService()
        url, state = service.build_auth_url()
        assert "https://accounts.spotify.com/authorize" in url
        assert "client_id=" in url
        assert "response_type=code" in url
        assert "state=" in url
        assert len(state) > 20

    def test_state_is_unique_per_call(self) -> None:
        service = SpotifyAuthService()
        _, state1 = service.build_auth_url()
        _, state2 = service.build_auth_url()
        assert state1 != state2

    def test_url_contains_scopes(self) -> None:
        service = SpotifyAuthService()
        url, _ = service.build_auth_url()
        assert "playlist-modify" in url


class TestBuildAuthHeader:
    def test_basic_auth_encoding(self) -> None:
        service = SpotifyAuthService()
        service._client_id = "test_id"
        service._client_secret = "test_secret"
        header = service._build_auth_header()
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

        with patch("app.services.spotify_auth.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            service = SpotifyAuthService()
            token = await service.exchange_code("auth_code_xyz")

        assert token.access_token == "access_123"
        assert token.refresh_token == "refresh_456"
        assert token.expires_in == 3600
        assert token.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_exchange_failure_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("app.services.spotify_auth.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            service = SpotifyAuthService()
            with pytest.raises(SpotifyAuthError, match="400"):
                await service.exchange_code("bad_code")


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

        with patch("app.services.spotify_auth.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            service = SpotifyAuthService()
            token = await service.refresh_access_token("old_refresh_token")

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

        with patch("app.services.spotify_auth.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(return_value=mock_response)

            service = SpotifyAuthService()
            token = await service.refresh_access_token("old_refresh")

        assert token.refresh_token == "rotated_refresh"


# ═══════════════════════════════════════════════════
#  Auth Routes — Integration Tests
# ═══════════════════════════════════════════════════

class TestLoginRoute:
    def test_login_returns_auth_url(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/login")
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state" in data
        assert "accounts.spotify.com" in data["auth_url"]


class TestCallbackRoute:
    def test_callback_success(self, client: TestClient) -> None:
        mock_token = TokenResponse(
            access_token="acc_123",
            refresh_token="ref_456",
            expires_in=3600,
            token_type="Bearer",
        )
        with patch.object(
            SpotifyAuthService, "exchange_code", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.get(
                "/api/v1/auth/callback",
                params={"code": "valid_code", "state": "valid_state"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "acc_123"
        assert data["refresh_token"] == "ref_456"

    def test_callback_spotify_error(self, client: TestClient) -> None:
        with patch.object(
            SpotifyAuthService,
            "exchange_code",
            new_callable=AsyncMock,
            side_effect=SpotifyAuthError("invalid_grant"),
        ):
            response = client.get(
                "/api/v1/auth/callback",
                params={"code": "bad_code", "state": "some_state"},
            )
        assert response.status_code == 502

    def test_callback_missing_code(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/callback", params={"state": "s"})
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
            SpotifyAuthService, "refresh_access_token", new_callable=AsyncMock, return_value=mock_token
        ):
            response = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "my_refresh_token"},
            )
        assert response.status_code == 200
        assert response.json()["access_token"] == "new_acc"

    def test_refresh_missing_body(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/refresh", json={})
        assert response.status_code == 422


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
