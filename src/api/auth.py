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

import hashlib
import logging
import os
import secrets as secrets_module
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.shared.config import load_companies
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)


def _hash_password(password: str) -> tuple[str, str]:
    """Hash a password with a random salt using PBKDF2."""
    salt = secrets_module.token_hex(32)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100_000
    ).hex()
    return hashed, salt


def _verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash."""
    return (
        hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100_000
        ).hex()
        == hashed
    )

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


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""


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

# Lazy-initialised storage (shared across requests)
_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


def _seed_user_if_new(username: str) -> None:
    """Copy the default companies list into the database for first-time users."""
    dynamo = _get_dynamo()
    if dynamo.get_user_companies(username) is not None:
        return  # User already has a saved list

    defaults = load_companies()
    companies = [
        {
            "name": c.name,
            "ticker": c.ticker,
            "sector": c.sector,
            "cik": c.cik,
            "investor_page_url": c.investor_page_url,
            "news_page_url": c.news_page_url,
        }
        for c in defaults
    ]
    dynamo.put_user_companies(username, companies)
    logger.info("Seeded %d default companies for new user %s", len(companies), username)


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """Authenticate with username + password and receive a JWT."""
    # 1. Check hardcoded admin credentials
    if body.username == ADMIN_USERNAME and body.password == ADMIN_PASSWORD:
        _seed_user_if_new(body.username)
        token = create_access_token(body.username)
        return TokenResponse(access_token=token, username=body.username)

    # 2. Check registered users in database
    dynamo = _get_dynamo()
    creds = dynamo.get_user_credentials(body.username)
    if creds and _verify_password(body.password, creds["hashed_password"], creds["salt"]):
        _seed_user_if_new(body.username)
        token = create_access_token(body.username)
        return TokenResponse(access_token=token, username=body.username)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


@auth_router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest):
    """Register a new user account."""
    username = body.username.strip()
    if not username or len(username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be at least 3 characters.",
        )
    if len(body.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters.",
        )
    # Check if username is reserved (admin)
    if username.lower() == ADMIN_USERNAME.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is not available.",
        )
    dynamo = _get_dynamo()
    if dynamo.user_exists(username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{username}' is already taken.",
        )
    hashed, salt = _hash_password(body.password)
    dynamo.put_user_credentials(username, hashed, salt, body.email)
    _seed_user_if_new(username)
    token = create_access_token(username)
    return TokenResponse(access_token=token, username=username)


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

    _seed_user_if_new(email)
    token = create_access_token(email)
    return TokenResponse(access_token=token, username=email)


@auth_router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)):
    """Return info about the currently authenticated user."""
    return UserInfo(username=user.get("sub", ""))
