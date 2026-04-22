"""Strategy interface — all platform integrations implement this contract."""

from abc import ABC, abstractmethod

from app.domain.models import Track


class MusicPlatform(ABC):
    """
    Abstract base for music platform integrations.

    Each concrete implementation (Spotify, YouTube, etc.) must fulfill
    this contract. The core processing logic depends only on this
    interface, never on concrete implementations (DIP).
    """

    @abstractmethod
    async def search_track(self, track: Track, access_token: str) -> Track:
        """Search for a track on the platform and populate platform_id/uri.

        Args:
            track: Track with at least raw_input populated.
            access_token: User's OAuth token for API authentication.

        Returns:
            The same Track with status, platform_id, platform_uri,
            and confidence updated.
        """

    @abstractmethod
    async def create_playlist(
        self,
        name: str,
        track_ids: list[str],
        access_token: str,
    ) -> tuple[str, list[str]]:
        """Create a playlist on the platform.

        Args:
            name: Desired playlist name.
            track_ids: Platform-specific track IDs to add.
            access_token: User's OAuth token.

        Returns:
            Tuple of (playlist_url, failed_ids) where failed_ids contains
            any track IDs that were found but could not be added to the
            playlist (e.g. due to quota exhaustion or API errors).
        """

    @abstractmethod
    async def get_user_id(self, access_token: str) -> str:
        """Retrieve the authenticated user's platform ID.

        Args:
            access_token: User's OAuth token.

        Returns:
            Platform-specific user identifier.
        """
