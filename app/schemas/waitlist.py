from pydantic import BaseModel, EmailStr, Field


class WaitlistEntryRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    contact_email: EmailStr
    spotify_email: EmailStr


class WaitlistEntryResponse(BaseModel):
    message: str


class WaitlistAdminEntry(BaseModel):
    id: str
    name: str
    contact_email: str
    spotify_email: str
    submitted_at: str
    approved: bool = False
    approved_at: str | None = None


class WaitlistAdminResponse(BaseModel):
    total: int
    entries: list[WaitlistAdminEntry]


class ApproveResponse(BaseModel):
    ok: bool
    message: str
