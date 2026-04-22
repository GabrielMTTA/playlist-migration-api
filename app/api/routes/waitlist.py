import hmac
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.schemas.waitlist import (
    ApproveResponse,
    WaitlistAdminEntry,
    WaitlistAdminResponse,
    WaitlistEntryRequest,
    WaitlistEntryResponse,
)
from app.services.email import send_approval_email

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])

WAITLIST_KEY = "tuneship:waitlist"
APPROVED_PREFIX = "tuneship:waitlist:approved:"
WAITLIST_MAX = 500


def _get_redis() -> aioredis.Redis:
    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        decode_responses=True,
    )


def _require_admin(request: Request) -> None:
    """Validates the X-Admin-Key header. Raises 403 on failure."""
    if not settings.waitlist_admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin key not configured.",
        )
    provided_key = request.headers.get("X-Admin-Key", "")
    if not hmac.compare_digest(provided_key, settings.waitlist_admin_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )


# ── Public ──────────────────────────────────────────────────────────────────

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
                "id": str(uuid.uuid4()),
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


# ── Admin ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=WaitlistAdminResponse,
)
async def get_waitlist(request: Request) -> WaitlistAdminResponse:
    """Retrieve all waitlist entries. Requires admin key."""
    _require_admin(request)

    r = _get_redis()
    try:
        raw_entries = await r.lrange(WAITLIST_KEY, 0, -1)

        entries: list[WaitlistAdminEntry] = []
        for raw in raw_entries:
            try:
                data = json.loads(raw)
                entry_id = data.get("id", "")
                approved_at = None
                approved = False

                if entry_id:
                    approved_at = await r.get(f"{APPROVED_PREFIX}{entry_id}")
                    approved = approved_at is not None

                entries.append(
                    WaitlistAdminEntry(
                        id=entry_id,
                        name=data.get("name", ""),
                        contact_email=data.get("contact_email", ""),
                        spotify_email=data.get("spotify_email", ""),
                        submitted_at=data.get("submitted_at", ""),
                        approved=approved,
                        approved_at=approved_at,
                    )
                )
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        await r.aclose()

    return WaitlistAdminResponse(total=len(entries), entries=entries)


@router.post(
    "/{entry_id}/approve",
    response_model=ApproveResponse,
)
async def approve_entry(entry_id: str, request: Request) -> ApproveResponse:
    """Approve a waitlist entry and send an access e-mail. Requires admin key."""
    _require_admin(request)

    r = _get_redis()
    try:
        # Check if already approved
        already = await r.get(f"{APPROVED_PREFIX}{entry_id}")
        if already:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este usuário já foi aprovado.",
            )

        # Find the entry in the list
        raw_entries = await r.lrange(WAITLIST_KEY, 0, -1)
        found: dict | None = None
        for raw in raw_entries:
            try:
                data = json.loads(raw)
                if data.get("id") == entry_id:
                    found = data
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Entrada não encontrada.",
            )

        # Mark as approved in Redis (no TTL — never evict)
        approved_at = datetime.now(timezone.utc).isoformat()
        await r.set(f"{APPROVED_PREFIX}{entry_id}", approved_at)
    finally:
        await r.aclose()

    # Send approval e-mail
    try:
        await send_approval_email(
            name=found["name"],
            contact_email=found["contact_email"],
        )
    except Exception as exc:  # noqa: BLE001
        # Roll back the approval flag so admin can retry
        r2 = _get_redis()
        try:
            await r2.delete(f"{APPROVED_PREFIX}{entry_id}")
        finally:
            await r2.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao enviar e-mail: {exc}",
        ) from exc

    return ApproveResponse(
        ok=True,
        message=f"Acesso aprovado e e-mail enviado para {found['contact_email']}.",
    )
