from pydantic import BaseModel, EmailStr, Field


class WaitlistEntryRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    contact_email: EmailStr
    spotify_email: EmailStr


class WaitlistEntryResponse(BaseModel):
    message: str


class WaitlistAdminEntry(BaseModel):
    name: str
    contact_email: str
    spotify_email: str
    submitted_at: str


class WaitlistAdminResponse(BaseModel):
    total: int
    entries: list[WaitlistAdminEntry]
