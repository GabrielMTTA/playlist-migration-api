"""Redis-based search cache — conserves YouTube API quota.

Each YouTube search costs 100 quota units (10k/day limit).
Caching results for 24h avoids redundant API calls when the
same track is searched multiple times across different jobs.
"""

import json
import logging

import redis

from app.core.config import settings
from app.domain.models import MatchCandidate

logger = logging.getLogger(__name__)

_KEY_PREFIX = "search_cache:"


def _get_redis() -> redis.Redis:
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        decode_responses=True,
    )


def _cache_key(platform: str, query: str) -> str:
    return f"{_KEY_PREFIX}{platform}:{query.lower().strip()}"


def cache_get(platform: str, query: str) -> list[MatchCandidate] | None:
    """Retrieve cached search results for a query.

    Returns:
        List of MatchCandidate if cache hit, None if miss.
    """
    try:
        client = _get_redis()
        raw = client.get(_cache_key(platform, query))
    except redis.RedisError as exc:
        logger.warning("Search cache read error: %s", exc)
        return None

    if raw is None:
        return None

    items = json.loads(raw)
    return [
        MatchCandidate(
            id=item["id"],
            uri=item["uri"],
            title=item["title"],
            artist=item["artist"],
        )
        for item in items
    ]


def cache_set(
    platform: str,
    query: str,
    candidates: list[MatchCandidate],
    ttl: int | None = None,
) -> None:
    """Store search results in cache.

    Args:
        platform: Platform identifier (e.g. "youtube_music").
        query: The search query string.
        candidates: Results to cache.
        ttl: Time-to-live in seconds (defaults to settings.search_cache_ttl).
    """
    if ttl is None:
        ttl = settings.search_cache_ttl

    items = [
        {"id": c.id, "uri": c.uri, "title": c.title, "artist": c.artist}
        for c in candidates
    ]

    try:
        client = _get_redis()
        client.setex(_cache_key(platform, query), ttl, json.dumps(items))
    except redis.RedisError as exc:
        logger.warning("Search cache write error: %s", exc)
