"""Domain models — platform-agnostic entities."""

from dataclasses import dataclass, field
from enum import Enum


class TrackStatus(str, Enum):
    PENDING = "pending"
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass
class Track:
    """A single track parsed from the input file."""

    raw_input: str
    title: str
    artist: str | None = None
    platform_id: str | None = None
    platform_uri: str | None = None
    status: TrackStatus = TrackStatus.PENDING
    confidence: float = 0.0


@dataclass
class PlaylistRequest:
    """Represents a full playlist creation job."""

    tracks: list[Track] = field(default_factory=list)
    playlist_name: str = "Imported Playlist"
    user_token: str = ""


@dataclass
class ProcessingResult:
    """Final report after playlist creation attempt."""

    total: int = 0
    found: int = 0
    not_found: int = 0
    errors: int = 0
    tracks: list[Track] = field(default_factory=list)
    playlist_url: str | None = None

    @property
    def success_rate(self) -> float:
        return (self.found / self.total * 100) if self.total > 0 else 0.0
