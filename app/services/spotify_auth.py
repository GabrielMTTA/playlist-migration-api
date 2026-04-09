"""Spotify OAuth 2.0 — Authorization Code Flow.

Handles:
  1. Generating the authorization URL (with PKCE-like state param)
  2. Exchanging the authorization code for access + refresh tokens
  3. Refreshing an expired access token
"""

import secrets
from dataclasses import dataclass
from base64 import b64encode

import httpx

from app.core.config import settings


class SpotifyAuthError(Exception):
    """Raised when Spotify auth operations fail."""


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str


class SpotifyAuthService:
    """Encapsulates all Spotify OAuth 2.0 operations."""

    def __init__(self) -> None:
        self._client_id = settings.spotify_client_id
        self._client_secret = settings.spotify_client_secret
        self._redirect_uri = settings.spotify_redirect_uri
        self._scopes = settings.spotify_scopes
        self._auth_url = settings.spotify_auth_url
        self._token_url = settings.spotify_token_url

    # ── Public ──

    def build_auth_url(self) -> tuple[str, str]:
        """Generate the Spotify authorization URL and a CSRF state token.

        Returns:
            Tuple of (authorization_url, state_token).
        """
        state = secrets.token_urlsafe(32)
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": self._scopes,
            "state": state,
            "show_dialog": "true",
        }
        query = "&".join(f"{k}={httpx.QueryParams({k: v})}" for k, v in params.items())
        # Use httpx to properly encode
        url = str(httpx.URL(self._auth_url, params=params))
        return url, state

    async def exchange_code(self, code: str) -> TokenResponse:
        """Exchange an authorization code for access and refresh tokens.

        Args:
            code: Authorization code received from Spotify callback.

        Returns:
            TokenResponse with access_token, refresh_token, etc.

        Raises:
            SpotifyAuthError: If the exchange fails.
        """
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        return await self._post_token(data)

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """Use a refresh token to obtain a new access token.

        Args:
            refresh_token: Valid refresh token from a previous auth flow.

        Returns:
            TokenResponse (refresh_token may be the same or rotated).

        Raises:
            SpotifyAuthError: If the refresh fails.
        """
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return await self._post_token(data)

    # ── Private ──

    def _build_auth_header(self) -> str:
        """Build Basic auth header from client credentials."""
        raw = f"{self._client_id}:{self._client_secret}"
        encoded = b64encode(raw.encode()).decode()
        return f"Basic {encoded}"

    async def _post_token(self, data: dict[str, str]) -> TokenResponse:
        """POST to Spotify's token endpoint.

        Raises:
            SpotifyAuthError: On any non-200 response or network error.
        """
        headers = {
            "Authorization": self._build_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    self._token_url,
                    data=data,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                raise SpotifyAuthError(
                    f"Network error contacting Spotify: {exc}"
                ) from exc

        if response.status_code != 200:
            raise SpotifyAuthError(
                f"Spotify token error ({response.status_code}): {response.text}"
            )

        body = response.json()
        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", data.get("refresh_token", "")),
            expires_in=body["expires_in"],
            token_type=body["token_type"],
        )
