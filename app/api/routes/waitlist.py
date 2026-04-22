import hmac
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.schemas.waitlist import (
    WaitlistAdminEntry,
    WaitlistAdminResponse,
    WaitlistEntryRequest,
    WaitlistEntryResponse,
)

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])

WAITLIST_KEY = "tuneship:waitlist"
WAITLIST_MAX = 500


def _get_redis() -> aioredis.Redis:
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        decode_responses=True,
    )


@router.post(
    "",
    response_model=WaitlistEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_waitlist(body: WaitlistEntryRequest) -> WaitlistEntryResponse:
    """Register a new entry on the waitlist."""
    r = _get_redis()
    try:
        total = await r.llen(WAITLIST_KEY)
        if total >= WAITLIST_MAX:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="A lista de espera está temporariamente fechada. Tente novamente em breve.",
            )

        entry = json.dumps(
            {
                "name": body.name,
                "contact_email": body.contact_email,
                "spotify_email": body.spotify_email,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await r.lpush(WAITLIST_KEY, entry)
    finally:
        await r.aclose()

    return WaitlistEntryResponse(
        message="Você está na lista! Entraremos em contato assim que uma vaga abrir."
    )


@router.get(
    "",
    response_model=WaitlistAdminResponse,
)
async def get_waitlist(request: Request) -> WaitlistAdminResponse:
    """Retrieve all waitlist entries. Requires admin key."""
    provided_key = request.headers.get("X-Admin-Key", "")

    if not settings.waitlist_admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin key not configured.",
        )

    if not hmac.compare_digest(provided_key, settings.waitlist_admin_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )

    r = _get_redis()
    try:
        raw_entries = await r.lrange(WAITLIST_KEY, 0, -1)
    finally:
        await r.aclose()

    entries: list[WaitlistAdminEntry] = []
    for raw in raw_entries:
        try:
            data = json.loads(raw)
            entries.append(WaitlistAdminEntry(**data))
        except (json.JSONDecodeError, TypeError):
            continue

    return WaitlistAdminResponse(total=len(entries), entries=entries)
