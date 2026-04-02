"""Factory for music platform strategy instances."""

from app.domain.interfaces import MusicPlatform
from app.schemas.playlist import PlatformEnum


class PlatformFactory:
    """Registry-based factory for MusicPlatform implementations.

    Platforms register themselves at application startup. This avoids
    hardcoding imports and makes adding new platforms a single-line change.
    """

    _registry: dict[PlatformEnum, type[MusicPlatform]] = {}

    @classmethod
    def register(cls, platform: PlatformEnum, impl: type[MusicPlatform]) -> None:
        cls._registry[platform] = impl

    @classmethod
    def create(cls, platform: PlatformEnum) -> MusicPlatform:
        impl_class = cls._registry.get(platform)
        if impl_class is None:
            raise ValueError(f"Platform '{platform.value}' is not registered")
        return impl_class()

    @classmethod
    def available_platforms(cls) -> list[str]:
        return [p.value for p in cls._registry]
