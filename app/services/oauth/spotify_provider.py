"""Spotify OAuth 2.0 — Authorization Code Flow.

Handles:
  1. Generating the authorization URL (with CSRF state param)
  2. Exchanging the authorization code for access + refresh tokens
  3. Refreshing an expired access token
"""

from base64 import b64encode

import httpx

from app.core.config import settings
from app.services.oauth.base import OAuthError, OAuthProvider, TokenResponse


class SpotifyOAuthProvider(OAuthProvider):
    """Spotify implementation of the OAuthProvider contract."""

    def __init__(self) -> None:
        self._client_id = settings.spotify_client_id
        self._client_secret = settings.spotify_client_secret
        self._redirect_uri = settings.spotify_redirect_uri
        self._scopes = settings.spotify_scopes
        self._auth_url = settings.spotify_auth_url
        self._token_url = settings.spotify_token_url

    # -- Public (OAuthProvider contract) --

    def build_auth_url(self) -> tuple[str, str]:
        state = self.generate_state()
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": self._scopes,
            "state": state,
            "show_dialog": "true",
        }
        url = str(httpx.URL(self._auth_url, params=params))
        return url, state

    async def exchange_code(self, code: str) -> TokenResponse:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        return await self._post_token(data)

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return await self._post_token(data)

    # -- Private --

    def _build_auth_header(self) -> str:
        raw = f"{self._client_id}:{self._client_secret}"
        encoded = b64encode(raw.encode()).decode()
        return f"Basic {encoded}"

    async def _post_token(self, data: dict[str, str]) -> TokenResponse:
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
                raise OAuthError(
                    f"Network error contacting Spotify: {exc}"
                ) from exc

        if response.status_code != 200:
            raise OAuthError(
                f"Spotify token error ({response.status_code}): {response.text}"
            )

        body = response.json()
        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", data.get("refresh_token", "")),
            expires_in=body["expires_in"],
            token_type=body["token_type"],
        )
