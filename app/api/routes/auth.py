"""Auth routes — OAuth 2.0 Authorization Code Flow (multi-platform)."""

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.schemas.auth import (
    AuthURLResponse,
    RefreshTokenRequest,
    TokenResponseSchema,
)
from app.schemas.playlist import PlatformEnum
from app.services.oauth import OAuthError, OAuthProviderFactory

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/{platform}/login", response_model=AuthURLResponse)
async def login(platform: PlatformEnum) -> AuthURLResponse:
    """Generate an authorization URL for the given platform.

    The client should redirect the user to `auth_url`.
    The `state` value must be stored client-side and validated in the callback
    to prevent CSRF attacks.
    """
    provider = _get_provider(platform)
    url, state = provider.build_auth_url()
    return AuthURLResponse(auth_url=url, state=state)


@router.get("/{platform}/callback")
async def callback(
    platform: PlatformEnum,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
):
    """Handle the OAuth callback for the given platform.

    Exchanges the authorization code for access + refresh tokens,
    then redirects to the frontend with tokens as query parameters.
    """
    provider = _get_provider(platform)
    try:
        token = await provider.exchange_code(code)
    except OAuthError as e:
        frontend_error_url = (
            f"{settings.frontend_url}/auth/callback"
            f"?error=auth_failed&platform={platform.value}"
        )
        return RedirectResponse(url=frontend_error_url)

    frontend_callback_url = (
        f"{settings.frontend_url}/auth/callback"
        f"?access_token={token.access_token}"
        f"&refresh_token={token.refresh_token}"
        f"&expires_in={token.expires_in}"
        f"&platform={platform.value}"
    )
    return RedirectResponse(url=frontend_callback_url)


@router.post("/{platform}/refresh", response_model=TokenResponseSchema)
async def refresh_token(
    platform: PlatformEnum,
    body: RefreshTokenRequest,
) -> TokenResponseSchema:
    """Refresh an expired access token for the given platform."""
    provider = _get_provider(platform)
    try:
        token = await provider.refresh_access_token(body.refresh_token)
    except OAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{platform.value} token refresh failed: {e}",
        )

    return TokenResponseSchema(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
        token_type=token.token_type,
    )


def _get_provider(platform: PlatformEnum):
    """Resolve an OAuthProvider from the factory or raise 404."""
    try:
        return OAuthProviderFactory.create(platform)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform '{platform.value}' has no registered OAuth provider",
        )
