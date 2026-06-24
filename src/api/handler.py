"""
Main API handler — FastAPI application served by Mangum on AWS Lambda.
"""

from __future__ import annotations

import logging
import os

# Configure logging before any module imports — Lambda defaults root to WARNING
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    force=True,
)

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from .auth import auth_router, get_current_user
from .routes import analysis, companies, dashboard, job_runs, pipeline

app = FastAPI(
    title="InvestingAssistant API",
    version="1.0.0",
    description="REST API for the InvestingAnalysisAgent dashboard.",
)

# CORS — permissive for development; CloudFront restricts in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth endpoints — no authentication required
app.include_router(auth_router, prefix="/api", tags=["Auth"])

# Protected route modules — require valid JWT
app.include_router(companies.router, prefix="/api", tags=["Companies"], dependencies=[Depends(get_current_user)])
app.include_router(analysis.router, prefix="/api", tags=["Analysis"], dependencies=[Depends(get_current_user)])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"], dependencies=[Depends(get_current_user)])
app.include_router(job_runs.router, prefix="/api", tags=["Job Runs"], dependencies=[Depends(get_current_user)])
app.include_router(pipeline.router, prefix="/api", tags=["Pipeline"], dependencies=[Depends(get_current_user)])


@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.on_event("startup")
def _cleanup_stale_jobs():
    """Mark any RUNNING jobs as CANCELLED on startup.

    When uvicorn restarts (e.g. --reload), background pipeline threads are
    killed silently, leaving job records stuck in RUNNING forever.  This
    cleanup runs once per process start to fix that.
    """
    import logging
    _log = logging.getLogger(__name__)
    try:
        from src.shared.storage import create_dynamo_storage
        dynamo = create_dynamo_storage()
        runs = dynamo.get_recent_job_runs(limit=100)
        stale = [r for r in runs if r.get("status") == "RUNNING"]
        for job in stale:
            run_id = job.get("run_id", "")
            dynamo.update_job_run(run_id, {
                "status": "CANCELLED",
                "cancel_requested": True,
            })
            _log.info("Cleaned up stale RUNNING job: %s", run_id)
        if stale:
            _log.info("Marked %d stale jobs as CANCELLED on startup", len(stale))
    except Exception as exc:
        _log.warning("Failed to clean up stale jobs: %s", exc)


@app.get("/api/health", tags=["Health"])
def api_health_check():
    """API health check."""
    return {"status": "ok", "service": "InvestingAssistant API"}


# AWS Lambda handler via Mangum
handler = Mangum(app, lifespan="off")
