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
    try:
        dynamo = _get_dynamo()
        dynamo.put_job_run(job)
        dynamo.update_job_run(run_id, {
            "triggered_by": triggered_by,
            "tickers": tickers,
            "trigger_type": "manual",
        })
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
    import time

    def _run():
        from src.shared.job_logger import JobLogger, Stage

        dynamo = _get_dynamo()
        jlog = JobLogger(run_id, storage=dynamo)
        tickers = [c.get('ticker', '?') for c in companies]
        jlog.info(Stage.INIT, f"Pipeline started for {len(companies)} companies",
                  triggered_by=triggered_by, tickers=tickers, mode="local")

        event = {"companies": companies, "triggered_by": triggered_by, "manual": True, "run_id": run_id}
        total_docs = 0
        errors = []
        all_s3_keys = []  # Collect S3 keys from all scraper stages

        # --- SEC Scraper ---
        jlog.stage_start(Stage.SEC_SCRAPER, len(companies))
        sec_docs = 0
        t0 = time.time()
        try:
            from src.scrapers.sec_agent.handler import handler as sec_handler
            jlog.info(Stage.SEC_SCRAPER, "SEC scraper module loaded successfully")

            for company in companies:
                ticker = company.get('ticker', '?')
                jlog.company_start(Stage.SEC_SCRAPER, ticker)
                ct = time.time()
                try:
                    result = sec_handler({"companies": [company]}, None)
                    found = result.get("scraped_count", 0)
                    new_keys = result.get("s3_keys", [])
                    result_errors = result.get("errors", [])
                    elapsed = int((time.time() - ct) * 1000)

                    sec_docs += len(new_keys)
                    all_s3_keys.extend(new_keys)
                    jlog.company_done(Stage.SEC_SCRAPER, ticker,
                                     docs_found=found, new_docs=len(new_keys))

                    if new_keys:
                        jlog.info(Stage.SEC_SCRAPER, f"{ticker}: uploaded {len(new_keys)} docs to storage",
                                  ticker=ticker, s3_keys=new_keys, elapsed_ms=elapsed)
                    elif found > 0:
                        jlog.info(Stage.SEC_SCRAPER, f"{ticker}: {found} filings found but all already processed",
                                  ticker=ticker, elapsed_ms=elapsed)
                    else:
                        jlog.info(Stage.SEC_SCRAPER, f"{ticker}: no filings of interest found",
                                  ticker=ticker, elapsed_ms=elapsed)

                    if result_errors:
                        for err in result_errors:
                            jlog.warn(Stage.SEC_SCRAPER, f"{ticker}: {err}", ticker=ticker)

                except Exception as exc:
                    jlog.company_error(Stage.SEC_SCRAPER, ticker, exc)

            total_docs += sec_docs
            jlog.stage_done(Stage.SEC_SCRAPER, sec_docs, int((time.time() - t0) * 1000))

        except Exception as exc:
            errors.append(f"SEC: {str(exc)}")
            jlog.error(Stage.SEC_SCRAPER, "SEC scraper import/init failed", exc=exc)

        # --- Company Info Scraper ---
        jlog.stage_start(Stage.COMPANY_INFO, len(companies))
        info_docs = 0
        t0 = time.time()
        try:
            from src.scrapers.company_info_agent.handler import handler as info_handler
            jlog.info(Stage.COMPANY_INFO, "Company info scraper module loaded successfully")

            for company in companies:
                ticker = company.get('ticker', '?')
                jlog.company_start(Stage.COMPANY_INFO, ticker)
                ct = time.time()
                try:
                    result = info_handler({"companies": [company]}, None)
                    body = result.get("body", result)
                    inv_scraped = body.get("investor_docs_scraped", 0)
                    news_scraped = body.get("news_docs_scraped", 0)
                    new_uploaded = body.get("new_documents_uploaded", 0)
                    s3_keys = body.get("s3_keys", [])
                    result_errors = body.get("errors", [])
                    elapsed = int((time.time() - ct) * 1000)

                    info_docs += len(s3_keys)
                    all_s3_keys.extend(s3_keys)
                    jlog.company_done(Stage.COMPANY_INFO, ticker,
                                     docs_found=inv_scraped + news_scraped,
                                     new_docs=new_uploaded)

                    jlog.info(Stage.COMPANY_INFO,
                              f"{ticker}: investor={inv_scraped} news={news_scraped} new={new_uploaded}",
                              ticker=ticker, investor_docs=inv_scraped, news_docs=news_scraped,
                              new_docs=new_uploaded, elapsed_ms=elapsed)

                    if s3_keys:
                        jlog.info(Stage.COMPANY_INFO, f"{ticker}: stored {len(s3_keys)} docs",
                                  ticker=ticker, s3_keys=s3_keys)

                    if result_errors:
                        for err in result_errors:
                            jlog.warn(Stage.COMPANY_INFO, f"{ticker}: {err}", ticker=ticker)

                except Exception as exc:
                    jlog.company_error(Stage.COMPANY_INFO, ticker, exc)

            total_docs += info_docs
            jlog.stage_done(Stage.COMPANY_INFO, info_docs, int((time.time() - t0) * 1000))

        except Exception as exc:
            errors.append(f"CompanyInfo: {str(exc)}")
            jlog.error(Stage.COMPANY_INFO, "Company info scraper import/init failed", exc=exc)

        # --- Sentiment Analysis ---
        jlog.stage_start(Stage.SENTIMENT, len(companies))
        analysis_results = 0
        analysis_errors = []
        t0 = time.time()
        try:
            from src.analyzers.sentiment_analyzer.handler import handler as sentiment_handler
            from src.analyzers.sentiment_analyzer.llm_client import _MODEL_MAP

            # Determine which LLM provider/model will be used
            primary_provider = "gemini"
            provider_name, model_id = _MODEL_MAP.get(primary_provider, ("gemini", "gemini-2.5-flash"))
            jlog.info(Stage.SENTIMENT, f"LLM analysis using {provider_name}/{model_id}",
                      provider=provider_name, model=model_id, fallback_chain=["openai/gpt-4o-mini", "anthropic/claude-3-5-haiku-latest"])

            if not all_s3_keys:
                jlog.info(Stage.SENTIMENT, "No scraped documents to analyze — skipping LLM analysis")
            else:
                jlog.info(Stage.SENTIMENT, f"Analyzing {len(all_s3_keys)} documents")
                ct = time.time()
                try:
                    result = sentiment_handler({"s3_keys": all_s3_keys, "primary_provider": primary_provider}, None)
                    processed = result.get("documents_processed", 0)
                    skipped = result.get("documents_skipped", 0)
                    llm_metrics = result.get("llm_metrics", [])
                    result_errors = result.get("errors", [])
                    result_ids = result.get("result_ids", [])
                    elapsed = int((time.time() - ct) * 1000)

                    analysis_results = processed

                    # Log per-document LLM details
                    for m in llm_metrics:
                        jlog.info(Stage.SENTIMENT,
                                  f"{m.get('provider', '?')}/{m.get('model', '?')} "
                                  f"tokens_in={m.get('tokens_in', 0)} tokens_out={m.get('tokens_out', 0)} "
                                  f"cost=${m.get('cost_usd', 0):.6f} latency={m.get('latency_ms', 0)}ms",
                                  provider=m.get('provider'), model=m.get('model'),
                                  tokens_in=m.get('tokens_in', 0), tokens_out=m.get('tokens_out', 0),
                                  cost_usd=m.get('cost_usd', 0), latency_ms=m.get('latency_ms', 0))

                    jlog.info(Stage.SENTIMENT,
                              f"Analysis complete: {processed} analyzed, {skipped} skipped, {elapsed}ms",
                              analyzed=processed, skipped=skipped, elapsed_ms=elapsed)

                    if result_errors:
                        for err in result_errors:
                            jlog.warn(Stage.SENTIMENT, err)
                            analysis_errors.append(err)

                except Exception as exc:
                    jlog.error(Stage.SENTIMENT, "Sentiment analysis failed", exc=exc)
                    errors.append(f"Sentiment: {str(exc)}")

            jlog.stage_done(Stage.SENTIMENT, analysis_results, int((time.time() - t0) * 1000))

        except Exception as exc:
            errors.append(f"Sentiment: {str(exc)}")
            jlog.error(Stage.SENTIMENT, "Sentiment analyzer import/init failed", exc=exc)

        # --- Impact Scoring ---
        jlog.stage_start(Stage.IMPACT_SCORER, len(companies))
        scored_count = 0
        alerts_count = 0
        t0 = time.time()
        try:
            from src.analyzers.impact_scorer.handler import handler as impact_handler
            jlog.info(Stage.IMPACT_SCORER, "Impact scorer module loaded successfully")

            tickers_for_scoring = [c.get('ticker', '?') for c in companies]
            ct = time.time()
            try:
                result = impact_handler({"tickers": tickers_for_scoring}, None)
                scored_count = result.get("scored_count", 0)
                alerts_count = result.get("alerts_triggered", 0)
                result_errors = result.get("errors", [])
                elapsed = int((time.time() - ct) * 1000)

                jlog.info(Stage.IMPACT_SCORER,
                          f"Scored {scored_count} results, {alerts_count} alerts triggered",
                          scored=scored_count, alerts=alerts_count, elapsed_ms=elapsed)

                if result_errors:
                    for err in result_errors:
                        jlog.warn(Stage.IMPACT_SCORER, err)

            except Exception as exc:
                jlog.error(Stage.IMPACT_SCORER, "Impact scoring failed", exc=exc)
                errors.append(f"ImpactScorer: {str(exc)}")

            jlog.stage_done(Stage.IMPACT_SCORER, scored_count, int((time.time() - t0) * 1000))

        except Exception as exc:
            errors.append(f"ImpactScorer: {str(exc)}")
            jlog.error(Stage.IMPACT_SCORER, "Impact scorer import/init failed", exc=exc)

        # --- Final Summary ---
        status = "FAILED" if errors and total_docs == 0 and analysis_results == 0 else "COMPLETED"
        jlog.info(Stage.COMPLETE if status == "COMPLETED" else Stage.INIT,
                  f"Pipeline {status.lower()}: {total_docs} scraped, {analysis_results} analyzed, {scored_count} scored, {len(errors)} errors",
                  total_docs=total_docs, analyses=analysis_results, scored=scored_count,
                  alerts=alerts_count, errors=errors)

        _update_job_status(run_id, status, errors, total_docs)
        # Also update analysis/scoring counts
        try:
            dynamo.update_job_run(run_id, {
                "analyses_completed": analysis_results,
                "documents_scraped": total_docs,
            })
        except Exception:
            pass
        jlog.flush()

        logger.info("Local pipeline finished (run_id=%s) status=%s docs=%d logs=%d",
                    run_id, status, total_docs, len(jlog.entries))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return run_id


def _update_job_status(run_id: str, status: str, errors: list[str] = None, docs_scraped: int = 0):
    """Update a job run's status in the database."""
    try:
        dynamo = _get_dynamo()
        updates = {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if errors:
            updates["errors"] = errors
        if docs_scraped > 0:
            updates["documents_scraped"] = docs_scraped
        dynamo.update_job_run(run_id, updates)
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
