"""
Company API routes.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.shared.config import load_companies, get_company_by_ticker
from src.shared.models import DataSource
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


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies():
    """List all tracked companies."""
    companies = load_companies()
    return [
        CompanyResponse(
            name=c.name,
            ticker=c.ticker,
            sector=c.sector,
            cik=c.cik,
            investor_page_url=c.investor_page_url,
            news_page_url=c.news_page_url,
        )
        for c in companies
    ]


@router.get("/companies/{ticker}", response_model=CompanyDetailResponse)
def get_company(ticker: str):
    """Get company details with latest analysis summary."""
    company = get_company_by_ticker(ticker.upper())
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
        name=company.name,
        ticker=company.ticker,
        sector=company.sector,
        cik=company.cik,
        investor_page_url=company.investor_page_url,
        news_page_url=company.news_page_url,
        analysis_count=len(analyses),
        latest_sentiment=latest.get("sentiment"),
        latest_impact_score=latest.get("impact_score"),
        source_breakdown=source_counts,
    )
