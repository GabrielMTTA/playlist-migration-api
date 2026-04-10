"""OAuth provider abstraction — all OAuth integrations implement this contract."""

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass


class OAuthError(Exception):
    """Raised when any OAuth provider operation fails."""


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str


class OAuthProvider(ABC):
    """Abstract base for OAuth 2.0 provider integrations.

    Each concrete implementation (Spotify, Google, etc.) must fulfill
    this contract. Auth routes depend only on this interface (DIP).
    """

    @abstractmethod
    def build_auth_url(self) -> tuple[str, str]:
        """Generate the provider's authorization URL and a CSRF state token.

        Returns:
            Tuple of (authorization_url, state_token).
        """

    @abstractmethod
    async def exchange_code(self, code: str) -> TokenResponse:
        """Exchange an authorization code for access and refresh tokens.

        Args:
            code: Authorization code received from the provider callback.

        Returns:
            TokenResponse with access_token, refresh_token, etc.

        Raises:
            OAuthError: If the exchange fails.
        """

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """Use a refresh token to obtain a new access token.

        Args:
            refresh_token: Valid refresh token from a previous auth flow.

        Returns:
            TokenResponse (refresh_token may be the same or rotated).

        Raises:
            OAuthError: If the refresh fails.
        """

    @staticmethod
    def generate_state() -> str:
        """Generate a cryptographically secure CSRF state token."""
        return secrets.token_urlsafe(32)
