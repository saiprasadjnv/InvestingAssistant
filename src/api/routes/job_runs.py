"""
Job run tracking API routes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


@router.get("/job-runs")
def list_job_runs(
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Recent pipeline execution history with LLM cost breakdown."""
    dynamo = _get_dynamo()

    try:
        runs = dynamo.get_recent_job_runs(limit=limit)
    except Exception as exc:
        logger.error("Failed to get job runs: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch job runs")

    # Compute aggregate cost stats
    total_cost = sum(r.get("total_cost_usd", 0.0) for r in runs)
    total_tokens_in = sum(r.get("total_tokens_in", 0) for r in runs)
    total_tokens_out = sum(r.get("total_tokens_out", 0) for r in runs)

    return {
        "count": len(runs),
        "aggregate_cost_usd": round(total_cost, 4),
        "aggregate_tokens_in": total_tokens_in,
        "aggregate_tokens_out": total_tokens_out,
        "runs": runs,
    }


@router.get("/job-runs/{run_id}")
def get_job_run(run_id: str) -> dict[str, Any]:
    """Get details for a specific job run."""
    dynamo = _get_dynamo()

    try:
        runs = dynamo.get_recent_job_runs(limit=100)
        for run in runs:
            if run.get("run_id") == run_id:
                return run
        raise HTTPException(status_code=404, detail=f"Job run {run_id} not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get job run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch job run")
