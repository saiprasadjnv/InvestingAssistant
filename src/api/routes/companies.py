"""
Company API routes — per-user company lists.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth import get_current_user
from src.shared.config import load_companies
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

# Lazy-initialise storage (reused across Lambda invocations)
_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


def _get_username(user: dict) -> str:
    """Extract the username (sub claim) from the JWT payload."""
    return user.get("sub", "anonymous")


def _get_user_companies_list(username: str) -> list[dict]:
    """Get companies for a user, seeding from defaults if first time."""
    dynamo = _get_dynamo()
    companies = dynamo.get_user_companies(username)
    if companies is None:
        # First-time user — seed from default config
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
    return companies


# --- Response models ---

class CompanyResponse(BaseModel):
    name: str
    ticker: str
    sector: str
    cik: str
    investor_page_url: Optional[str] = None
    news_page_url: Optional[str] = None


class CompanyDetailResponse(CompanyResponse):
    analysis_count: int = 0
    latest_sentiment: Optional[str] = None
    latest_impact_score: Optional[float] = None
    source_breakdown: dict[str, int] = {}


class CompanyCreateRequest(BaseModel):
    name: str
    ticker: str
    sector: str = "Unknown"
    cik: str = ""
    investor_page_url: Optional[str] = None
    news_page_url: Optional[str] = None


# --- Endpoints ---

@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(user: dict = Depends(get_current_user)):
    """List the authenticated user's tracked companies."""
    username = _get_username(user)
    companies = _get_user_companies_list(username)
    return [CompanyResponse(**c) for c in companies]


@router.get("/companies/{ticker}", response_model=CompanyDetailResponse)
def get_company(ticker: str, user: dict = Depends(get_current_user)):
    """Get company details with latest analysis summary."""
    username = _get_username(user)
    companies = _get_user_companies_list(username)

    company = next((c for c in companies if c["ticker"].upper() == ticker.upper()), None)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    dynamo = _get_dynamo()
    try:
        analyses = dynamo.get_analyses_for_ticker(ticker.upper(), limit=50)
    except Exception as exc:
        logger.error("Failed to fetch analyses for %s: %s", ticker, exc)
        analyses = []

    # Build source breakdown
    source_counts: dict[str, int] = {}
    for a in analyses:
        src = a.get("source", "UNKNOWN")
        source_counts[src] = source_counts.get(src, 0) + 1

    latest = analyses[0] if analyses else {}

    return CompanyDetailResponse(
        **company,
        analysis_count=len(analyses),
        latest_sentiment=latest.get("sentiment"),
        latest_impact_score=latest.get("impact_score"),
        source_breakdown=source_counts,
    )


@router.post("/companies", response_model=CompanyResponse, status_code=201)
def create_company(body: CompanyCreateRequest, user: dict = Depends(get_current_user)):
    """Add a new company to the authenticated user's tracked list."""
    username = _get_username(user)
    dynamo = _get_dynamo()

    new_company = {
        "name": body.name,
        "ticker": body.ticker,
        "sector": body.sector,
        "cik": body.cik,
        "investor_page_url": body.investor_page_url,
        "news_page_url": body.news_page_url,
    }

    try:
        # Ensure user has a list first (seeds defaults if needed)
        _get_user_companies_list(username)
        dynamo.add_user_company(username, new_company)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return CompanyResponse(**new_company)


@router.delete("/companies/{ticker}")
def delete_company(ticker: str, user: dict = Depends(get_current_user)):
    """Remove a company from the authenticated user's tracked list."""
    username = _get_username(user)
    dynamo = _get_dynamo()

    try:
        # Ensure user has a list first
        _get_user_companies_list(username)
        dynamo.remove_user_company(username, ticker)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found")

    return {"detail": f"Company {ticker.upper()} removed", "ticker": ticker.upper()}
