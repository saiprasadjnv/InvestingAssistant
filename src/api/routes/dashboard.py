"""
Dashboard aggregate API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from src.api.auth import get_current_user
from src.shared.storage import create_dynamo_storage

from .helpers import get_user_companies_list

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


def _get_username(user: dict) -> str:
    """Extract the username (sub claim) from the JWT payload."""
    return user.get("sub", "anonymous")




@router.get("/dashboard/summary")
def get_dashboard_summary(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Aggregated dashboard data: company count, sentiment distribution, averages."""
    username = _get_username(user)
    companies = get_user_companies_list(username)
    dynamo = _get_dynamo()

    total_analyses = 0
    sentiment_distribution = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    impact_scores: list[float] = []
    company_summaries: list[dict] = []

    # Pre-fetch recent job runs for per-company status
    try:
        recent_runs = dynamo.get_recent_job_runs(limit=50)
    except Exception:
        recent_runs = []

    def _latest_run_for_ticker(ticker: str) -> dict | None:
        """Find the most recent job run that includes this ticker."""
        ticker_upper = ticker.upper()
        for run in recent_runs:  # Already sorted by started_at desc
            run_tickers = [t.upper() for t in run.get("tickers", [])]
            if ticker_upper in run_tickers:
                return run
        return None

    for company in companies:
        ticker = company["ticker"]
        name = company["name"]
        sector = company.get("sector", "Unknown")
        try:
            analyses = dynamo.get_analyses_for_ticker(ticker, limit=20)
            total_analyses += len(analyses)

            for a in analyses:
                s = a.get("sentiment", "NEUTRAL")
                sentiment_distribution[s] = sentiment_distribution.get(s, 0) + 1
                score = a.get("impact_score", 0.0)
                if isinstance(score, (int, float)):
                    impact_scores.append(score)

            latest = analyses[0] if analyses else {}
            latest_run = _latest_run_for_ticker(ticker)
            company_summaries.append({
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "analysis_count": len(analyses),
                "latest_sentiment": latest.get("sentiment"),
                "latest_impact_score": latest.get("impact_score"),
                "latest_run_status": latest_run.get("status") if latest_run else None,
                "latest_run_at": latest_run.get("started_at") if latest_run else None,
                "latest_run_id": latest_run.get("run_id") if latest_run else None,
            })
        except Exception as exc:
            logger.error("Failed to get analyses for %s: %s", ticker, exc)
            company_summaries.append({
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "analysis_count": 0,
                "latest_sentiment": None,
                "latest_impact_score": None,
                "latest_run_status": None,
                "latest_run_at": None,
                "latest_run_id": None,
            })

    avg_impact = sum(impact_scores) / len(impact_scores) if impact_scores else 0.0

    return {
        "total_companies": len(companies),
        "total_analyses": total_analyses,
        "sentiment_distribution": sentiment_distribution,
        "average_impact_score": round(avg_impact, 4),
        "companies": company_summaries,
    }


@router.get("/dashboard/top-findings")
def get_top_findings(
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Top high-confidence findings across all companies."""
    dynamo = _get_dynamo()

    try:
        findings = dynamo.get_top_findings(limit=limit)
    except Exception as exc:
        logger.error("Failed to get top findings: %s", exc)
        findings = []

    return {
        "count": len(findings),
        "findings": findings,
    }
