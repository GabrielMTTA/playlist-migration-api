"""Google OAuth 2.0 — Authorization Code Flow (YouTube Music).

Handles:
  1. Generating the Google authorization URL (with CSRF state param)
  2. Exchanging the authorization code for access + refresh tokens
  3. Refreshing an expired access token
"""

import httpx

from app.core.config import settings
from app.services.oauth.base import OAuthError, OAuthProvider, TokenResponse


class GoogleOAuthProvider(OAuthProvider):
    """Google implementation of the OAuthProvider contract."""

    def __init__(self) -> None:
        self._client_id = settings.google_client_id
        self._client_secret = settings.google_client_secret
        self._redirect_uri = settings.google_redirect_uri
        self._scopes = settings.google_scopes
        self._auth_url = settings.google_auth_url
        self._token_url = settings.google_token_url

    # -- Public (OAuthProvider contract) --

    def build_auth_url(self) -> tuple[str, str]:
        state = self.generate_state()
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": self._scopes,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        url = str(httpx.URL(self._auth_url, params=params))
        return url, state

    async def exchange_code(self, code: str) -> TokenResponse:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        return await self._post_token(data)

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        return await self._post_token(data)

    # -- Private --

    async def _post_token(self, data: dict[str, str]) -> TokenResponse:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    self._token_url,
                    data=data,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                raise OAuthError(
                    f"Network error contacting Google: {exc}"
                ) from exc

        if response.status_code != 200:
            raise OAuthError(
                f"Google token error ({response.status_code}): {response.text}"
            )

        body = response.json()
        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token", data.get("refresh_token", "")),
            expires_in=body.get("expires_in", 3600),
            token_type=body.get("token_type", "Bearer"),
        )
