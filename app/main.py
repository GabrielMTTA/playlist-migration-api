from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.playlist import router as playlist_router
from app.core.config import settings
from app.schemas.playlist import PlatformEnum
from app.services.oauth import GoogleOAuthProvider, OAuthProviderFactory, SpotifyOAuthProvider
from app.services.platform_factory import PlatformFactory
from app.services.spotify_client import SpotifyClient
from app.services.youtube_music_client import YouTubeMusicClient

app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

# -- Register platform implementations --
PlatformFactory.register(PlatformEnum.SPOTIFY, SpotifyClient)
PlatformFactory.register(PlatformEnum.YOUTUBE_MUSIC, YouTubeMusicClient)

# -- Register OAuth providers --
OAuthProviderFactory.register(PlatformEnum.SPOTIFY, SpotifyOAuthProvider)
OAuthProviderFactory.register(PlatformEnum.YOUTUBE_MUSIC, GoogleOAuthProvider)

app.include_router(auth_router)
app.include_router(playlist_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
