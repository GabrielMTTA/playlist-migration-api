"""Pydantic schemas for auth endpoints."""

from pydantic import BaseModel


class AuthURLResponse(BaseModel):
    auth_url: str
    state: str


class TokenResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str
