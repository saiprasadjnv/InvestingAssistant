"""
Job run tracking API routes.

Syncs Step Functions execution status in real-time:
- Job status is checked against the actual SFN execution
- Logs are read directly from SFN execution history (no DynamoDB storage)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from fastapi import APIRouter, HTTPException, Query

from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None
_sfn_client = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


def _get_sfn_client():
    global _sfn_client
    if _sfn_client is None:
        _sfn_client = boto3.client("stepfunctions")
    return _sfn_client


def _get_exec_arn(run_id: str) -> str | None:
    """Build execution ARN from run_id."""
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
    if not state_machine_arn or not run_id.startswith("manual-"):
        return None
    base_arn = state_machine_arn.replace(":stateMachine:", ":execution:")
    return f"{base_arn}:{run_id}"


def _sync_job_status(run_id: str, run: dict) -> dict:
    """Check SFN execution and update job status in DynamoDB if changed."""
    exec_arn = _get_exec_arn(run_id)
    if not exec_arn or run.get("status") not in ("RUNNING",):
        return run

    try:
        sfn = _get_sfn_client()
        execution = sfn.describe_execution(executionArn=exec_arn)
        sfn_status = execution.get("status", "RUNNING")

        if sfn_status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
            status_map = {
                "SUCCEEDED": "COMPLETED",
                "FAILED": "FAILED",
                "TIMED_OUT": "FAILED",
                "ABORTED": "CANCELLED",
            }
            new_status = status_map.get(sfn_status, "FAILED")

            stop_date = execution.get("stopDate")
            completed_at = (
                stop_date.isoformat()
                if isinstance(stop_date, datetime)
                else datetime.now(timezone.utc).isoformat()
            )

            updates = {"status": new_status, "completed_at": completed_at}

            # Extract stats from output
            try:
                output = json.loads(execution.get("output", "{}") or "{}")
                updates["analyses_completed"] = output.get("scored_count", 0)
            except Exception:
                pass

            _get_dynamo().update_job_run(run_id, updates)
            run.update(updates)

    except Exception as exc:
        logger.debug("SFN sync failed for %s: %s", run_id, exc)

    return run


def _get_sfn_logs(run_id: str) -> list[dict]:
    """Read logs directly from Step Functions execution history. No DynamoDB."""
    exec_arn = _get_exec_arn(run_id)
    if not exec_arn:
        return []

    try:
        sfn = _get_sfn_client()
        history = sfn.get_execution_history(
            executionArn=exec_arn,
            maxResults=100,
            reverseOrder=False,
        )

        logs = []
        for event in history.get("events", []):
            entry = _event_to_log(event)
            if entry:
                entry["run_id"] = run_id
                logs.append(entry)

        return logs

    except Exception as exc:
        logger.debug("Failed to read SFN logs for %s: %s", run_id, exc)
        return []


def _event_to_log(event: dict) -> dict | None:
    """Convert a Step Functions event to a log entry."""
    event_type = event.get("type", "")
    ts = event.get("timestamp", datetime.now(timezone.utc))
    ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)

    message = None
    level = "INFO"

    if event_type == "ExecutionStarted":
        message = "🚀 Pipeline started"

    elif event_type == "ParallelStateEntered":
        message = "📊 Starting parallel scrapers (SEC, Company Info, Reddit, X)..."

    elif event_type == "ParallelStateExited":
        message = "📊 All scrapers finished"

    elif event_type == "TaskStateEntered":
        name = event.get("stateEnteredEventDetails", {}).get("name", "")
        label = {
            "RunSECAgent": "📄 SEC EDGAR scraper starting...",
            "RunCompanyInfoAgent": "🏢 Company info scraper starting...",
            "RunRedditAgent": "💬 Reddit scraper starting...",
            "RunXAgent": "🐦 X/Twitter scraper starting...",
            "RunSentimentAnalyzer": "🧠 Sentiment analysis starting...",
            "RunImpactScorer": "📈 Impact scoring starting...",
        }.get(name)
        if label:
            message = label

    elif event_type == "TaskSucceeded":
        output_str = event.get("taskSucceededEventDetails", {}).get("output", "{}")
        try:
            payload = json.loads(output_str).get("Payload", {})
            if "s3_keys" in payload:
                count = len(payload["s3_keys"])
                message = f"✅ Scraper done — {count} documents uploaded to S3"
            elif "body" in payload and isinstance(payload["body"], dict):
                body = payload["body"]
                count = body.get("new_documents_uploaded", 0)
                companies = body.get("companies_processed", 0)
                message = f"✅ Company info done — {count} docs from {companies} companies"
            elif "result_ids" in payload:
                processed = payload.get("documents_processed", 0)
                skipped = payload.get("documents_skipped", 0)
                errors = len(payload.get("errors", []))
                message = f"🧠 Sentiment done — {processed} analyzed, {skipped} skipped, {errors} errors"
            elif "scored_count" in payload:
                scored = payload.get("scored_count", 0)
                message = f"📈 Impact scoring done — {scored} results scored"
            else:
                message = "✅ Task completed"
        except Exception:
            message = "✅ Task completed"

    elif event_type == "TaskFailed":
        level = "ERROR"
        cause = event.get("taskFailedEventDetails", {}).get("cause", "Unknown")
        try:
            err_msg = json.loads(cause).get("errorMessage", cause[:120])
        except Exception:
            err_msg = cause[:120]
        message = f"❌ Task failed: {err_msg}"

    elif event_type == "PassStateEntered":
        name = event.get("stateEnteredEventDetails", {}).get("name", "")
        if "Collect" in name:
            message = "📋 Collecting documents for analysis..."
        elif "Fallback" in name or "Error" in name:
            level = "WARNING"
            message = f"⚠️ {name.replace('ErrorFallback', ' scraper failed — continuing with others')}"

    elif event_type == "ExecutionSucceeded":
        message = "✅ Pipeline completed successfully"

    elif event_type == "ExecutionFailed":
        level = "ERROR"
        message = "❌ Pipeline failed"

    elif event_type == "ExecutionAborted":
        level = "WARNING"
        message = "🛑 Pipeline cancelled"

    if not message:
        return None

    return {"timestamp": ts_str, "stage": "PIPELINE", "level": level, "message": message}


# ---------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------

@router.get("/job-runs")
def list_job_runs(
    limit: int = Query(20, ge=1, le=100),
    ticker: Optional[str] = Query(None, description="Filter by company ticker"),
) -> dict[str, Any]:
    """Recent pipeline execution history with LLM cost breakdown."""
    dynamo = _get_dynamo()

    try:
        runs = dynamo.get_recent_job_runs(limit=limit)
    except Exception as exc:
        logger.error("Failed to get job runs: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch job runs")

    # Sync SFN status for RUNNING jobs
    runs = [_sync_job_status(r.get("run_id", ""), r) for r in runs]

    if ticker:
        ticker_upper = ticker.upper()
        runs = [r for r in runs if ticker_upper in [t.upper() for t in r.get("tickers", [])]]

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
                return _sync_job_status(run_id, run)
        raise HTTPException(status_code=404, detail=f"Job run {run_id} not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get job run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch job run")


@router.get("/job-runs/{run_id}/logs")
def get_job_run_logs(run_id: str) -> dict[str, Any]:
    """Get log entries — reads directly from Step Functions execution history."""
    # Try SFN first (real-time, no storage needed)
    entries = _get_sfn_logs(run_id)

    # Fallback to DynamoDB logs (for local pipeline runs)
    if not entries:
        try:
            dynamo = _get_dynamo()
            entries = dynamo.get_job_logs(run_id)
        except Exception as exc:
            logger.error("Failed to get logs for %s: %s", run_id, exc)
            raise HTTPException(status_code=500, detail="Failed to fetch job logs")

    return {
        "run_id": run_id,
        "entry_count": len(entries),
        "entries": entries,
    }
