"""Factory for OAuth provider instances."""

from app.schemas.playlist import PlatformEnum
from app.services.oauth.base import OAuthProvider


class OAuthProviderFactory:
    """Registry-based factory for OAuthProvider implementations.

    Mirrors PlatformFactory: providers register at startup,
    routes resolve by platform key at request time.
    """

    _registry: dict[PlatformEnum, type[OAuthProvider]] = {}

    @classmethod
    def register(cls, platform: PlatformEnum, impl: type[OAuthProvider]) -> None:
        cls._registry[platform] = impl

    @classmethod
    def create(cls, platform: PlatformEnum) -> OAuthProvider:
        impl_class = cls._registry.get(platform)
        if impl_class is None:
            raise ValueError(
                f"No OAuth provider registered for '{platform.value}'"
            )
        return impl_class()

    @classmethod
    def available_platforms(cls) -> list[str]:
        return [p.value for p in cls._registry]
