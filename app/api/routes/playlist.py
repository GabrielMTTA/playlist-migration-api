"""Playlist routes — file upload, JSON creation, task status, and reports."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import PlainTextResponse

from app.api.dependencies import require_access_token
from app.schemas.playlist import (
    PlatformEnum,
    PlaylistCreateRequest,
    PlaylistCreateResponse,
    TaskStatusResponse,
)
from app.services.file_parser import parse_file_content
from app.services.report_generator import generate_structured_report, generate_text_report
from app.workers.tasks import process_playlist

router = APIRouter(prefix="/api/v1/playlists", tags=["playlists"])

# Max file size: 1 MB
MAX_FILE_SIZE = 1_048_576


def _dispatch_task(
    track_dicts: list[dict],
    platform: PlatformEnum,
    playlist_name: str,
    access_token: str,
) -> str:
    """Dispatch a Celery task and return its ID."""
    task = process_playlist.delay(
        track_entries=track_dicts,
        platform=platform.value,
        playlist_name=playlist_name,
        access_token=access_token,
    )
    return task.id


@router.post(
    "/upload",
    response_model=PlaylistCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_playlist_from_file(
    file: UploadFile = File(...),
    platform: PlatformEnum = Form(PlatformEnum.SPOTIFY),
    playlist_name: str = Form("Imported Playlist"),
    access_token: str = Depends(require_access_token),
) -> PlaylistCreateResponse:
    """Upload a .txt file to create a playlist.

    Each line should contain a track in one of these formats:
    - `Artist - Title`
    - `Title`
    """
    if file.content_type not in ("text/plain",):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .txt files are accepted",
        )

    raw_bytes = await file.read()

    if len(raw_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 1 MB limit",
        )

    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded",
        )

    try:
        tracks = parse_file_content(content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    track_dicts = [
        {"raw_input": t.raw_input, "title": t.title, "artist": t.artist}
        for t in tracks
    ]
    task_id = _dispatch_task(track_dicts, platform, playlist_name, access_token)

    return PlaylistCreateResponse(task_id=task_id)


@router.post(
    "/",
    response_model=PlaylistCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_playlist_from_json(
    body: PlaylistCreateRequest,
    access_token: str = Depends(require_access_token),
) -> PlaylistCreateResponse:
    """Create a playlist from a JSON payload of track names."""
    track_dicts = [
        {"raw_input": name, "title": name, "artist": None}
        for name in body.track_names
    ]
    task_id = _dispatch_task(
        track_dicts, body.platform, body.playlist_name, access_token,
    )

    return PlaylistCreateResponse(task_id=task_id)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Poll the status of a playlist processing task."""
    result = process_playlist.AsyncResult(task_id)

    if result.state == "PENDING":
        return TaskStatusResponse(task_id=task_id, status="pending")

    if result.state == "PROGRESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="processing",
            result=result.info,
        )

    if result.state == "SUCCESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="completed",
            result=result.result,
        )

    # FAILURE or other states
    return TaskStatusResponse(
        task_id=task_id,
        status="failed",
        result={"error": str(result.info)},
    )


def _get_completed_result(task_id: str) -> dict:
    """Retrieve a completed task result or raise 404/409."""
    result = process_playlist.AsyncResult(task_id)

    if result.state == "PENDING":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or still pending",
        )

    if result.state in ("STARTED", "PROGRESS"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is still processing",
        )

    if result.state == "FAILURE":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task failed: {result.info}",
        )

    return result.result


@router.get("/tasks/{task_id}/report")
async def get_task_report(task_id: str) -> dict:
    """Get a structured JSON report for a completed task."""
    raw_result = _get_completed_result(task_id)
    return generate_structured_report(raw_result)


@router.get(
    "/tasks/{task_id}/report/text",
    response_class=PlainTextResponse,
)
async def get_task_report_text(task_id: str) -> str:
    """Get a human-readable plain-text report for a completed task."""
    raw_result = _get_completed_result(task_id)
    return generate_text_report(raw_result)
