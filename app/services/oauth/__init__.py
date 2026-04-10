"""OAuth provider package — public API."""

from app.services.oauth.base import OAuthError, OAuthProvider, TokenResponse
from app.services.oauth.factory import OAuthProviderFactory
from app.services.oauth.google_provider import GoogleOAuthProvider
from app.services.oauth.spotify_provider import SpotifyOAuthProvider

__all__ = [
    "GoogleOAuthProvider",
    "OAuthError",
    "OAuthProvider",
    "OAuthProviderFactory",
    "SpotifyOAuthProvider",
    "TokenResponse",
]
