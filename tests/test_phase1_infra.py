"""Phase 1 — Infrastructure & Boilerplate Tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


# ── Health Check ──

class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_payload(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.json() == {"status": "healthy"}


# ── Settings ──

class TestSettings:
    def test_default_values(self) -> None:
        s = Settings(
            debug=False,
            redis_password="test",
            spotify_client_id="id",
            spotify_client_secret="secret",
        )
        assert s.debug is False
        assert s.redis_port == 6379

    def test_redis_url_construction(self) -> None:
        s = Settings(
            redis_password="s3cret",
            redis_host="myhost",
            redis_port=6380,
            spotify_client_id="id",
            spotify_client_secret="secret",
        )
        assert s.redis_url == "redis://:s3cret@myhost:6380/0"

    def test_celery_urls_fallback_to_redis(self) -> None:
        s = Settings(
            redis_password="pw",
            spotify_client_id="id",
            spotify_client_secret="secret",
        )
        assert s.get_celery_broker_url() == s.redis_url
        assert s.get_celery_result_backend() == s.redis_url

    def test_celery_urls_explicit_override(self) -> None:
        s = Settings(
            redis_password="pw",
            spotify_client_id="id",
            spotify_client_secret="secret",
            celery_broker_url="redis://custom:6379/1",
            celery_result_backend="redis://custom:6379/2",
        )
        assert s.get_celery_broker_url() == "redis://custom:6379/1"
        assert s.get_celery_result_backend() == "redis://custom:6379/2"


# ── Project Structure ──

class TestProjectStructure:
    """Verifies the expected directory layout exists."""

    ROOT = Path(__file__).resolve().parent.parent

    @pytest.mark.parametrize(
        "path",
        [
            "app/__init__.py",
            "app/main.py",
            "app/core/config.py",
            "app/api/__init__.py",
            "app/api/routes/__init__.py",
            "app/domain/__init__.py",
            "app/services/__init__.py",
            "app/workers/celery_app.py",
            "app/schemas/__init__.py",
            "Dockerfile",
            "docker-compose.yml",
            "nginx/nginx.conf",
            "requirements.txt",
        ],
    )
    def test_required_file_exists(self, path: str) -> None:
        assert (self.ROOT / path).exists(), f"Missing: {path}"
