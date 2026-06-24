"""
Pipeline trigger API routes — allows users to manually run analysis.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth import get_current_user
from src.shared.models import JobRunMetrics
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

        def _check_cancelled():
            """Check if cancellation was requested via storage flag."""
            try:
                runs = dynamo.get_recent_job_runs(limit=50)
                job = next((r for r in runs if r.get("run_id") == run_id), None)
                if job and job.get("cancel_requested"):
                    jlog.warn(Stage.INIT, "Pipeline cancelled by user")
                    _update_job_status(run_id, "CANCELLED", [], total_docs)
                    jlog.flush()
                    return True
            except Exception:
                pass
            return False

        if _check_cancelled(): return

        # --- SEC Scraper ---
        jlog.stage_start(Stage.SEC_SCRAPER, len(companies))
        sec_docs = 0
        t0 = time.time()
        try:
            from src.scrapers.sec_agent.handler import handler as sec_handler
            jlog.info(Stage.SEC_SCRAPER, "SEC scraper module loaded successfully")

            for company in companies:
                if _check_cancelled(): return
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

        if _check_cancelled(): return

        # --- Company Info Scraper ---
        jlog.stage_start(Stage.COMPANY_INFO, len(companies))
        info_docs = 0
        t0 = time.time()
        try:
            from src.scrapers.company_info_agent.handler import handler as info_handler
            jlog.info(Stage.COMPANY_INFO, "Company info scraper module loaded successfully")

            for company in companies:
                if _check_cancelled(): return
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

        if _check_cancelled(): return

        # --- Sentiment Analysis ---
        jlog.stage_start(Stage.SENTIMENT, len(companies))
        analysis_results = 0
        analysis_errors = []
        t0 = time.time()
        try:
            from src.analyzers.sentiment_analyzer.handler import _process_document, _parse_llm_response
            from src.analyzers.sentiment_analyzer.llm_client import LLMClient, _MODEL_MAP
            from src.shared.storage import create_file_storage
            from src.shared.models import DataSource as DS

            # Determine which LLM provider/model will be used
            primary_provider = "gemini"
            provider_name, model_id = _MODEL_MAP.get(primary_provider, ("gemini", "gemini-2.5-flash"))
            jlog.info(Stage.SENTIMENT, f"LLM analysis using {provider_name}/{model_id}",
                      provider=provider_name, model=model_id,
                      fallback_chain=["openai/gpt-4o-mini", "anthropic/claude-haiku-4-5-20251001"])

            # Collect ALL documents for these tickers (not just new ones)
            file_storage = create_file_storage()
            all_docs_for_analysis = []
            for company in companies:
                ticker = company.get('ticker', '?')
                for source in [DS.SEC, DS.INVESTOR_PAGE, DS.NEWS_PAGE]:
                    try:
                        docs = file_storage.list_documents(source, ticker)
                        all_docs_for_analysis.extend(docs)
                    except Exception:
                        pass

            if not all_docs_for_analysis:
                jlog.info(Stage.SENTIMENT, "No documents found for analysis")
            else:
                jlog.info(Stage.SENTIMENT, f"Found {len(all_docs_for_analysis)} documents to check",
                          total_docs=len(all_docs_for_analysis))

                # Initialize LLM client and process one-by-one with streaming logs
                llm_client = LLMClient(primary_provider=primary_provider)
                skipped = 0

                for doc_idx, s3_key in enumerate(all_docs_for_analysis, 1):
                    if _check_cancelled(): return

                    try:
                        doc = file_storage.download_document(s3_key)
                        doc_label = f"{doc.ticker}/{doc.source.value}/{doc.doc_id[:12]}"

                        # Check if already analyzed
                        if dynamo.is_document_processed(doc.source, doc.doc_id):
                            skipped += 1
                            jlog.info(Stage.SENTIMENT,
                                      f"[{doc_idx}/{len(all_docs_for_analysis)}] {doc_label} — already analyzed, skipping",
                                      ticker=doc.ticker, doc_id=doc.doc_id)
                            continue

                        jlog.info(Stage.SENTIMENT,
                                  f"[{doc_idx}/{len(all_docs_for_analysis)}] Analyzing {doc_label}...",
                                  ticker=doc.ticker, source=doc.source.value, doc_id=doc.doc_id)
                        jlog.flush()  # Flush so UI sees it immediately

                        ct = time.time()
                        import asyncio
                        result_id, metrics = asyncio.run(
                            _process_document(doc, llm_client, dynamo)
                        )
                        elapsed = int((time.time() - ct) * 1000)

                        if result_id and metrics:
                            analysis_results += 1
                            jlog.info(Stage.SENTIMENT,
                                      f"[{doc_idx}/{len(all_docs_for_analysis)}] ✓ {doc_label} — "
                                      f"{metrics.provider}/{metrics.model} "
                                      f"tokens={metrics.tokens_in}→{metrics.tokens_out} "
                                      f"cost=${metrics.cost_usd:.6f} {elapsed}ms",
                                      ticker=doc.ticker, provider=metrics.provider,
                                      model=metrics.model, tokens_in=metrics.tokens_in,
                                      tokens_out=metrics.tokens_out, cost_usd=metrics.cost_usd,
                                      latency_ms=elapsed, result_id=result_id)
                        else:
                            skipped += 1
                            jlog.info(Stage.SENTIMENT,
                                      f"[{doc_idx}/{len(all_docs_for_analysis)}] — {doc_label} skipped (no template/result)",
                                      ticker=doc.ticker)

                        jlog.flush()  # Flush after each doc so logs stream

                    except Exception as exc:
                        error_msg = f"Error analyzing {s3_key}: {exc}"
                        jlog.error(Stage.SENTIMENT, error_msg, exc=exc)
                        analysis_errors.append(error_msg)
                        jlog.flush()

                jlog.info(Stage.SENTIMENT,
                          f"Analysis complete: {analysis_results} analyzed, {skipped} skipped, "
                          f"{len(analysis_errors)} errors, {int((time.time() - t0) * 1000)}ms total",
                          analyzed=analysis_results, skipped=skipped,
                          errors_count=len(analysis_errors))

            jlog.stage_done(Stage.SENTIMENT, analysis_results, int((time.time() - t0) * 1000))

        except Exception as exc:
            errors.append(f"Sentiment: {str(exc)}")
            jlog.error(Stage.SENTIMENT, "Sentiment analyzer import/init failed", exc=exc)

        if _check_cancelled(): return

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


@router.post("/pipeline/cancel/{run_id}", response_model=RunResponse)
def cancel_job(run_id: str, user: dict = Depends(get_current_user)):
    """Cancel a running pipeline job by setting a persistent flag in storage."""
    dynamo = _get_dynamo()

    # Verify the job exists and is running
    try:
        runs = dynamo.get_recent_job_runs(limit=50)
        job = next((r for r in runs if r.get("run_id") == run_id), None)
    except Exception as exc:
        logger.error("Failed to look up job %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Failed to look up job")

    if not job:
        raise HTTPException(status_code=404, detail=f"No job found with id {run_id}")

    if job.get("status") not in ("RUNNING", None):
        raise HTTPException(status_code=400, detail=f"Job is not running (status: {job.get('status')})")

    # Set the cancel flag in storage — the pipeline thread reads this
    try:
        dynamo.update_job_run(run_id, {"cancel_requested": True})
    except Exception as exc:
        logger.error("Failed to set cancel flag for %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Failed to set cancel flag")

    logger.info("Cancel flag set for job %s", run_id)
    return RunResponse(
        status="cancelling",
        message=f"Cancel signal sent to job {run_id}. It will stop after the current operation.",
        execution_id=run_id,
    )


@router.post("/pipeline/run", response_model=RunResponse)
def run_all_companies(user: dict = Depends(get_current_user)):
    """Trigger analysis for all companies the user is tracking."""
    username = user.get("sub", "")
    companies = get_user_companies_list(username)

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
    companies = get_user_companies_list(username)

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
