"""FastAPI dependencies — shared across routes."""

from fastapi import Header, HTTPException, status


async def require_access_token(
    authorization: str = Header(..., description="Bearer <access_token>"),
) -> str:
    """Extract and validate the Bearer token from the Authorization header.

    Returns:
        The raw access token string.

    Raises:
        HTTPException 401: If the header is missing or malformed.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use 'Bearer <token>' format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token
