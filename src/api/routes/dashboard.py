"""
Dashboard aggregate API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Query

from src.shared.config import load_companies
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


@router.get("/dashboard/summary")
def get_dashboard_summary() -> dict[str, Any]:
    """Aggregated dashboard data: company count, sentiment distribution, averages."""
    companies = load_companies()
    dynamo = _get_dynamo()

    total_analyses = 0
    sentiment_distribution = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    impact_scores: list[float] = []
    company_summaries: list[dict] = []

    for company in companies:
        try:
            analyses = dynamo.get_analyses_for_ticker(company.ticker, limit=20)
            total_analyses += len(analyses)

            for a in analyses:
                s = a.get("sentiment", "NEUTRAL")
                sentiment_distribution[s] = sentiment_distribution.get(s, 0) + 1
                score = a.get("impact_score", 0.0)
                if isinstance(score, (int, float)):
                    impact_scores.append(score)

            latest = analyses[0] if analyses else {}
            company_summaries.append({
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "analysis_count": len(analyses),
                "latest_sentiment": latest.get("sentiment"),
                "latest_impact_score": latest.get("impact_score"),
            })
        except Exception as exc:
            logger.error("Failed to get analyses for %s: %s", company.ticker, exc)
            company_summaries.append({
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "analysis_count": 0,
                "latest_sentiment": None,
                "latest_impact_score": None,
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
