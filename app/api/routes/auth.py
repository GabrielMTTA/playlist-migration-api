"""Auth routes — Spotify OAuth 2.0 Authorization Code Flow."""

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.auth import (
    AuthURLResponse,
    RefreshTokenRequest,
    TokenResponseSchema,
)
from app.services.spotify_auth import SpotifyAuthError, SpotifyAuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _get_auth_service() -> SpotifyAuthService:
    return SpotifyAuthService()


@router.get("/login", response_model=AuthURLResponse)
async def login() -> AuthURLResponse:
    """Generate a Spotify authorization URL.

    The client should redirect the user to `auth_url`.
    The `state` value must be stored client-side and validated in the callback
    to prevent CSRF attacks.
    """
    service = _get_auth_service()
    url, state = service.build_auth_url()
    return AuthURLResponse(auth_url=url, state=state)


@router.get("/callback", response_model=TokenResponseSchema)
async def callback(
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
) -> TokenResponseSchema:
    """Handle Spotify's OAuth callback.

    Exchanges the authorization code for access + refresh tokens.

    Note: In production, the `state` parameter should be validated against
    the value stored during /login. This validation is the client's
    responsibility (the API is stateless).
    """
    service = _get_auth_service()
    try:
        token = await service.exchange_code(code)
    except SpotifyAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Spotify auth failed: {e}",
        )

    return TokenResponseSchema(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
        token_type=token.token_type,
    )


@router.post("/refresh", response_model=TokenResponseSchema)
async def refresh_token(body: RefreshTokenRequest) -> TokenResponseSchema:
    """Refresh an expired access token."""
    service = _get_auth_service()
    try:
        token = await service.refresh_access_token(body.refresh_token)
    except SpotifyAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Spotify token refresh failed: {e}",
        )

    return TokenResponseSchema(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
        token_type=token.token_type,
    )
