"""
JWT-based authentication for the InvestingAssistant API.

Provides:
- JWT creation / verification utilities
- Login endpoint (username + password)
- Google Sign-In endpoint (Google ID token)
- ``/me`` endpoint
- ``get_current_user`` FastAPI dependency for protecting routes
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JWT_SECRET: str = os.environ.get("JWT_SECRET", "investing-assistant-dev-secret-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_HOURS: int = 24

ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "admin")

ALLOWED_EMAILS: list[str] | None = (
    [e.strip() for e in os.environ["ALLOWED_EMAILS"].split(",")]
    if "ALLOWED_EMAILS" in os.environ
    else None
)

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_access_token(username: str) -> str:
    """Create a signed JWT for *username* that expires in 24 hours."""
    payload: dict[str, Any] = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises ``jwt.PyJWTError`` on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleLoginRequest(BaseModel):
    credential: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    username: str


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency that enforces a valid JWT on protected routes.

    Extracts the ``Authorization: Bearer <token>`` header, verifies the JWT,
    and returns the decoded payload.  Raises ``HTTPException(401)`` if the
    token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = verify_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["Auth"])


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """Authenticate with username + password and receive a JWT."""
    if body.username != ADMIN_USERNAME or body.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(body.username)
    return TokenResponse(access_token=token, username=body.username)


@auth_router.post("/google", response_model=TokenResponse)
async def google_login(body: GoogleLoginRequest):
    """Authenticate with a Google ID token and receive a JWT."""
    # Verify the Google ID token via Google's tokeninfo endpoint
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.credential},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        )

    google_payload = resp.json()

    # Ensure the email is verified
    if str(google_payload.get("email_verified", "false")).lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google email not verified",
        )

    email: str = google_payload.get("email", "")

    # Optional: restrict to allowed emails
    if ALLOWED_EMAILS is not None and email not in ALLOWED_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not in allow-list",
        )

    token = create_access_token(email)
    return TokenResponse(access_token=token, username=email)


@auth_router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)):
    """Return info about the currently authenticated user."""
    return UserInfo(username=user.get("sub", ""))
