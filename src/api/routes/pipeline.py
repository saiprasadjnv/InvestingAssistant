"""
Pipeline trigger API routes — allows users to manually run analysis.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth import get_current_user
from src.shared.models import JobRunMetrics
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


class RunResponse(BaseModel):
    status: str
    message: str
    execution_id: str = ""


def _trigger_pipeline(companies: list[dict], triggered_by: str) -> str:
    """
    Start the pipeline for the given companies.

    In AWS: starts a Step Functions execution.
    Locally: runs scrapers directly in a background thread.
    """
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")

    # Record a job run entry
    run_id = f"manual-{uuid.uuid4().hex[:8]}"
    tickers = [c.get("ticker", "?") for c in companies]
    job = JobRunMetrics(
        run_id=run_id,
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
        companies_processed=len(companies),
    )
    # Store extra metadata directly on the item
    try:
        dynamo = _get_dynamo()
        dynamo.put_job_run(job)
        # Store tickers + triggered_by as additional metadata
        dynamo._job_runs_table.update_item(
            Key={"PK": f"RUN#{run_id}", "SK": "SUMMARY"},
            UpdateExpression="SET triggered_by = :tb, tickers = :tk, trigger_type = :tt",
            ExpressionAttributeValues={
                ":tb": triggered_by,
                ":tk": tickers,
                ":tt": "manual",
            },
        )
    except Exception as exc:
        logger.error("Failed to record job run: %s", exc)

    if state_machine_arn:
        return _start_step_functions(companies, triggered_by, state_machine_arn, run_id)
    else:
        return _run_local_pipeline(companies, triggered_by, run_id)


def _start_step_functions(companies: list[dict], triggered_by: str, arn: str, run_id: str) -> str:
    """Start a Step Functions execution (AWS mode)."""
    import boto3

    try:
        response = boto3.client("stepfunctions").start_execution(
            stateMachineArn=arn,
            name=run_id,
            input=json.dumps({
                "run_id": run_id,
                "companies": companies,
                "triggered_by": triggered_by,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "manual": True,
            }),
        )
        return run_id
    except Exception as exc:
        logger.error("Failed to start pipeline execution: %s", exc)
        # Update job run to FAILED
        _update_job_status(run_id, "FAILED", [str(exc)])
        raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {str(exc)}")


def _run_local_pipeline(companies: list[dict], triggered_by: str, run_id: str) -> str:
    """Run scrapers directly in a background thread (local mode)."""
    import threading

    def _run():
        event = {"companies": companies, "triggered_by": triggered_by, "manual": True, "run_id": run_id}
        docs_scraped = 0
        errors = []
        logger.info("Local pipeline started (run_id=%s) for %d companies", run_id, len(companies))

        try:
            from src.scrapers.sec_agent.handler import handler as sec_handler
            result = sec_handler(event, None)
            docs_scraped += len(result.get("s3_keys", []))
            logger.info("SEC scraper complete: %s", result)
        except Exception as exc:
            errors.append(f"SEC: {str(exc)}")
            logger.error("SEC scraper failed: %s", exc)

        try:
            from src.scrapers.company_info_agent.handler import handler as info_handler
            result = info_handler(event, None)
            docs_scraped += len(result.get("s3_keys", []))
            logger.info("Company info scraper complete: %s", result)
        except Exception as exc:
            errors.append(f"CompanyInfo: {str(exc)}")
            logger.error("Company info scraper failed: %s", exc)

        # Update the job run with final results
        status = "FAILED" if errors and docs_scraped == 0 else "COMPLETED"
        _update_job_status(run_id, status, errors, docs_scraped)
        logger.info("Local pipeline finished (run_id=%s) status=%s docs=%d", run_id, status, docs_scraped)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return run_id


def _update_job_status(run_id: str, status: str, errors: list[str] = None, docs_scraped: int = 0):
    """Update a job run's status in the database."""
    try:
        dynamo = _get_dynamo()
        update_expr = "SET #st = :s, completed_at = :ca"
        expr_values = {
            ":s": status,
            ":ca": datetime.now(timezone.utc).isoformat(),
        }
        expr_names = {"#st": "status"}
        if errors:
            update_expr += ", errors = :e"
            expr_values[":e"] = errors
        if docs_scraped > 0:
            update_expr += ", documents_scraped = :ds"
            expr_values[":ds"] = docs_scraped

        dynamo._job_runs_table.update_item(
            Key={"PK": f"RUN#{run_id}", "SK": "SUMMARY"},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ExpressionAttributeNames=expr_names,
        )
    except Exception as exc:
        logger.error("Failed to update job run %s: %s", run_id, exc)


@router.post("/pipeline/run", response_model=RunResponse)
def run_all_companies(user: dict = Depends(get_current_user)):
    """Trigger analysis for all companies the user is tracking."""
    username = user.get("sub", "")
    dynamo = _get_dynamo()
    companies = dynamo.get_user_companies(username)

    if not companies:
        raise HTTPException(status_code=400, detail="No companies in your tracking list.")

    execution_id = _trigger_pipeline(companies, username)

    return RunResponse(
        status="started",
        message=f"Analysis started for {len(companies)} companies. Results will appear shortly.",
        execution_id=execution_id,
    )


@router.post("/pipeline/run/{ticker}", response_model=RunResponse)
def run_single_company(ticker: str, user: dict = Depends(get_current_user)):
    """Trigger analysis for a single company."""
    username = user.get("sub", "")
    dynamo = _get_dynamo()
    companies = dynamo.get_user_companies(username) or []

    # Find the company by ticker
    company = next((c for c in companies if c["ticker"].upper() == ticker.upper()), None)
    if not company:
        raise HTTPException(
            status_code=404,
            detail=f"Company '{ticker}' not found in your tracking list.",
        )

    execution_id = _trigger_pipeline([company], username)

    return RunResponse(
        status="started",
        message=f"Analysis started for {company['name']} ({ticker.upper()}). Results will appear shortly.",
        execution_id=execution_id,
    )
