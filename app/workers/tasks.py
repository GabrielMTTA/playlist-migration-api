"""Celery tasks — playlist processing pipeline.

This module bridges the sync Celery world with our async domain logic
using asyncio.run().
"""

import asyncio
import logging
from dataclasses import asdict

from app.domain.models import Track, TrackStatus, ProcessingResult
from app.schemas.playlist import PlatformEnum
from app.services.platform_factory import PlatformFactory
from app.services.spotify_client import SpotifyClient
from app.workers.celery_app import celery

logger = logging.getLogger(__name__)

# Register platforms in worker context
PlatformFactory.register(PlatformEnum.SPOTIFY, SpotifyClient)


@celery.task(
    bind=True,
    name="process_playlist",
    max_retries=2,
    default_retry_delay=30,
    rate_limit="5/s",
)
def process_playlist(
    self: celery.Task,
    track_entries: list[dict],
    platform: str,
    playlist_name: str,
    access_token: str,
) -> dict:
    """Main Celery task: search tracks and create a playlist.

    Args:
        track_entries: List of dicts with 'raw_input', 'title', 'artist' keys.
        platform: Platform identifier (e.g. 'spotify').
        playlist_name: Name for the created playlist.
        access_token: User's OAuth access token.

    Returns:
        Serialized ProcessingResult as dict.
    """
    return asyncio.run(
        _process_playlist_async(
            self, track_entries, platform, playlist_name, access_token,
        )
    )


async def _process_playlist_async(
    task: celery.Task,
    track_entries: list[dict],
    platform: str,
    playlist_name: str,
    access_token: str,
) -> dict:
    """Async implementation of the playlist processing pipeline."""
    platform_enum = PlatformEnum(platform)
    client = PlatformFactory.create(platform_enum)

    tracks = [
        Track(
            raw_input=entry["raw_input"],
            title=entry["title"],
            artist=entry.get("artist"),
        )
        for entry in track_entries
    ]

    # ── Step 1: Search all tracks ──
    result = ProcessingResult(total=len(tracks))
    found_ids: list[str] = []

    for i, track in enumerate(tracks):
        try:
            searched = await client.search_track(track, access_token)
        except Exception as exc:
            logger.error("Search error for '%s': %s", track.raw_input, exc)
            track.status = TrackStatus.ERROR
            searched = track

        tracks[i] = searched

        if searched.status == TrackStatus.FOUND and searched.platform_id:
            result.found += 1
            found_ids.append(searched.platform_id)
        elif searched.status == TrackStatus.NOT_FOUND:
            result.not_found += 1
        else:
            result.errors += 1

        # Update Celery task progress metadata
        task.update_state(
            state="PROGRESS",
            meta={
                "current": i + 1,
                "total": result.total,
                "found": result.found,
            },
        )

    # ── Step 2: Create playlist with found tracks ──
    if found_ids:
        try:
            playlist_url = await client.create_playlist(
                name=playlist_name,
                track_ids=found_ids,
                access_token=access_token,
            )
            result.playlist_url = playlist_url
        except Exception as exc:
            logger.error("Playlist creation failed: %s", exc)

    result.tracks = tracks

    return _serialize_result(result)


def _serialize_result(result: ProcessingResult) -> dict:
    """Convert ProcessingResult to a JSON-serializable dict."""
    return {
        "total": result.total,
        "found": result.found,
        "not_found": result.not_found,
        "errors": result.errors,
        "success_rate": result.success_rate,
        "playlist_url": result.playlist_url,
        "tracks": [
            {
                "raw_input": t.raw_input,
                "status": t.status.value,
                "platform_id": t.platform_id,
                "platform_uri": t.platform_uri,
                "confidence": t.confidence,
            }
            for t in result.tracks
        ],
    }
