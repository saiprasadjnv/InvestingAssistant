"""
Analysis result API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.shared.models import DataSource
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


@router.get("/analysis/{ticker}")
def get_analysis(
    ticker: str,
    source: Optional[str] = Query(None, description="Filter by source: SEC, INVESTOR_PAGE, NEWS_PAGE, REDDIT, X"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Get all analysis findings for a company, optionally filtered by source."""
    dynamo = _get_dynamo()

    source_enum = None
    if source:
        try:
            source_enum = DataSource(source.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Valid values: {[s.value for s in DataSource]}",
            )

    try:
        results = dynamo.get_analyses_for_ticker(
            ticker.upper(), source=source_enum, limit=limit
        )
    except Exception as exc:
        logger.error("Failed to get analyses for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch analysis results")

    return {
        "ticker": ticker.upper(),
        "source_filter": source,
        "count": len(results),
        "results": results,
    }


@router.get("/analysis/{ticker}/history")
def get_analysis_history(
    ticker: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Get historical analysis timeline for a company with sentiment trends."""
    dynamo = _get_dynamo()

    try:
        results = dynamo.get_analyses_for_ticker(ticker.upper(), limit=limit)
    except Exception as exc:
        logger.error("Failed to get history for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch history")

    # Build sentiment trend data
    sentiment_counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    impact_scores = []
    timeline: list[dict] = []

    for r in results:
        sentiment = r.get("sentiment", "NEUTRAL")
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

        score = r.get("impact_score", 0.0)
        if isinstance(score, (int, float)):
            impact_scores.append(score)

        timeline.append({
            "created_at": r.get("created_at"),
            "source": r.get("source"),
            "sentiment": sentiment,
            "impact_score": score,
            "summary": r.get("summary", ""),
        })

    avg_impact = sum(impact_scores) / len(impact_scores) if impact_scores else 0.0

    return {
        "ticker": ticker.upper(),
        "total_analyses": len(results),
        "sentiment_distribution": sentiment_counts,
        "average_impact_score": round(avg_impact, 4),
        "timeline": timeline,
    }
