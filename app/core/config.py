from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── App ──
    app_name: str = "Playlist Migration API"
    debug: bool = False

    # ── Redis ──
    redis_password: str = "changeme"
    redis_host: str = "redis"
    redis_port: int = 6379

    # ── Spotify OAuth 2.0 ──
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8080/api/v1/auth/callback"
    spotify_scopes: str = "playlist-modify-public playlist-modify-private"
    spotify_auth_url: str = "https://accounts.spotify.com/authorize"
    spotify_token_url: str = "https://accounts.spotify.com/api/token"
    spotify_api_base_url: str = "https://api.spotify.com/v1"

    # ── Celery ──
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    def get_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    def get_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
