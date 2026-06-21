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

    if state_machine_arn:
        return _start_step_functions(companies, triggered_by, state_machine_arn)
    else:
        return _run_local_pipeline(companies, triggered_by)


def _start_step_functions(companies: list[dict], triggered_by: str, arn: str) -> str:
    """Start a Step Functions execution (AWS mode)."""
    import boto3

    execution_name = f"manual-{triggered_by[:20]}-{uuid.uuid4().hex[:8]}"

    try:
        response = boto3.client("stepfunctions").start_execution(
            stateMachineArn=arn,
            name=execution_name,
            input=json.dumps({
                "companies": companies,
                "triggered_by": triggered_by,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "manual": True,
            }),
        )
        return response["executionArn"].split(":")[-1]
    except Exception as exc:
        logger.error("Failed to start pipeline execution: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {str(exc)}")


def _run_local_pipeline(companies: list[dict], triggered_by: str) -> str:
    """Run scrapers directly in a background thread (local mode)."""
    import threading

    run_id = uuid.uuid4().hex[:8]

    def _run():
        event = {"companies": companies, "triggered_by": triggered_by, "manual": True}
        logger.info("Local pipeline started (run_id=%s) for %d companies", run_id, len(companies))
        try:
            from src.scrapers.sec_agent.handler import handler as sec_handler
            result = sec_handler(event, None)
            logger.info("SEC scraper complete: %s", result)
        except Exception as exc:
            logger.error("SEC scraper failed: %s", exc)

        try:
            from src.scrapers.company_info_agent.handler import handler as info_handler
            result = info_handler(event, None)
            logger.info("Company info scraper complete: %s", result)
        except Exception as exc:
            logger.error("Company info scraper failed: %s", exc)

        logger.info("Local pipeline finished (run_id=%s)", run_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return f"local-{run_id}"


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
