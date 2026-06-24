"""
Job run tracking API routes.

- Syncs Step Functions execution status in real-time
- Streams logs from CloudWatch Lambda log groups (the actual scraper/analyzer logs)
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import boto3
from fastapi import APIRouter, HTTPException, Query

from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None
_sfn_client = None
_logs_client = None

# Lambda log groups to read from
LAMBDA_LOG_GROUPS = [
    "/aws/lambda/InvestingAssistant-SECAgent",
    "/aws/lambda/InvestingAssistant-CompanyInfoAgent",
    "/aws/lambda/InvestingAssistant-RedditAgent",
    "/aws/lambda/InvestingAssistant-XAgent",
    "/aws/lambda/InvestingAssistant-SentimentAnalyzer",
    "/aws/lambda/InvestingAssistant-ImpactScorer",
]

# Map log group to friendly stage name
LOG_GROUP_STAGE = {
    "SECAgent": "SEC",
    "CompanyInfoAgent": "COMPANY",
    "RedditAgent": "REDDIT",
    "XAgent": "X",
    "SentimentAnalyzer": "SENTIMENT",
    "ImpactScorer": "IMPACT",
}


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


def _get_logs_client():
    global _logs_client
    if _logs_client is None:
        _logs_client = boto3.client("logs")
    return _logs_client


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

            try:
                output = json.loads(execution.get("output", "{}") or "{}")
                updates["analyses_completed"] = output.get("scored_count", 0)
            except Exception:
                pass

            _get_dynamo().update_job_run(run_id, updates)
            run.update(updates)

    except Exception as exc:
        logger.warning("SFN sync failed for %s: %s", run_id, exc)

    return run


def _get_execution_time_range(run_id: str) -> tuple[int, int] | None:
    """Get the start/end timestamps (ms) of a Step Functions execution."""
    exec_arn = _get_exec_arn(run_id)
    if not exec_arn:
        return None

    try:
        sfn = _get_sfn_client()
        execution = sfn.describe_execution(executionArn=exec_arn)
        start_time = execution.get("startDate")
        stop_time = execution.get("stopDate")

        if not start_time:
            return None

        # Convert to epoch milliseconds
        start_ms = int(start_time.timestamp() * 1000) - 2000  # 2s before
        if stop_time:
            end_ms = int(stop_time.timestamp() * 1000) + 2000  # 2s after
        else:
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        return (start_ms, end_ms)

    except Exception as exc:
        logger.warning("Failed to get execution time range for %s: %s", run_id, exc)
        return None


def _parse_cloudwatch_message(message: str, log_group: str) -> dict | None:
    """Parse a CloudWatch log line into a structured log entry."""
    # Skip Lambda platform messages
    if message.startswith(("START ", "END ", "REPORT ", "INIT_START", "XRAY")):
        return None

    # Extract stage from log group
    stage = "PIPELINE"
    for key, val in LOG_GROUP_STAGE.items():
        if key in log_group:
            stage = val
            break

    # Parse structured Lambda log: [LEVEL] timestamp requestId message
    # Format: [INFO] 2026-06-24T06:28:11.048Z requestId message
    m = re.match(
        r'\[(\w+)\]\s+(\S+)\s+\S+\s+(.*)',
        message.strip(),
    )
    if m:
        level = m.group(1).upper()
        msg = m.group(3).strip()
        # Skip noisy/internal messages
        if not msg or msg.startswith("Found credentials"):
            return None
        return {"level": level, "stage": stage, "msg": msg}

    # Also try: timestamp [LEVEL] name — message (from basicConfig)
    m2 = re.match(
        r'\S+\s+\[(\w+)\]\s+\S+\s+[—-]\s+(.*)',
        message.strip(),
    )
    if m2:
        level = m2.group(1).upper()
        msg = m2.group(2).strip()
        if not msg or msg.startswith("Found credentials"):
            return None
        return {"level": level, "stage": stage, "msg": msg}

    # Plain text log line
    msg = message.strip()
    if not msg or len(msg) < 5:
        return None
    return {"level": "INFO", "stage": stage, "msg": msg}


def _get_cloudwatch_logs(run_id: str) -> list[dict]:
    """Read actual Lambda CloudWatch logs for the execution time window."""
    time_range = _get_execution_time_range(run_id)
    if not time_range:
        return []

    start_ms, end_ms = time_range
    logs_client = _get_logs_client()
    all_entries = []

    for log_group in LAMBDA_LOG_GROUPS:
        try:
            # Filter log events from this log group in the time range
            paginator = logs_client.get_paginator("filter_log_events")
            for page in paginator.paginate(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                interleaved=True,
                PaginationConfig={"MaxItems": 200},
            ):
                for event in page.get("events", []):
                    parsed = _parse_cloudwatch_message(
                        event.get("message", ""), log_group
                    )
                    if parsed:
                        # Use CloudWatch timestamp (ms since epoch) → ISO string
                        ts_ms = event.get("timestamp", start_ms)
                        ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                        parsed["ts"] = ts_dt.isoformat()
                        parsed["run_id"] = run_id
                        all_entries.append(parsed)

        except logs_client.exceptions.ResourceNotFoundException:
            # Log group doesn't exist yet
            continue
        except Exception as exc:
            logger.debug("Failed to read logs from %s: %s", log_group, exc)
            continue

    # Sort by timestamp
    all_entries.sort(key=lambda e: e.get("ts", ""))
    return all_entries


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
    """Stream logs from CloudWatch Lambda log groups for this pipeline run."""
    # Try CloudWatch logs (real Lambda output)
    entries = _get_cloudwatch_logs(run_id)

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
