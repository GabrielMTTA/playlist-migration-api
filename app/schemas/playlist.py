"""Pydantic schemas for API request/response validation."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class PlatformEnum(str, Enum):
    SPOTIFY = "spotify"
    YOUTUBE_MUSIC = "youtube_music"


class PlaylistCreateRequest(BaseModel):
    """Schema for playlist creation via JSON (alternative to file upload)."""

    platform: PlatformEnum
    playlist_name: str = Field(
        default="Imported Playlist",
        min_length=1,
        max_length=200,
    )
    track_names: list[str] = Field(..., min_length=1, max_length=500)

    @field_validator("track_names")
    @classmethod
    def sanitize_track_names(cls, v: list[str]) -> list[str]:
        sanitized: list[str] = []
        for name in v:
            clean = name.strip()
            if clean:
                sanitized.append(clean[:300])
        if not sanitized:
            raise ValueError("At least one non-empty track name is required")
        return sanitized


class TrackResultSchema(BaseModel):
    raw_input: str
    status: str
    platform_id: str | None = None
    platform_uri: str | None = None
    confidence: float = 0.0


class PlaylistCreateResponse(BaseModel):
    task_id: str
    message: str = "Playlist creation job queued"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


class ProcessingReportSchema(BaseModel):
    total: int
    found: int
    not_found: int
    errors: int
    success_rate: float
    playlist_url: str | None = None
    tracks: list[TrackResultSchema]
