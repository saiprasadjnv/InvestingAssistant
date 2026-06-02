"""
Main API handler — FastAPI application served by Mangum on AWS Lambda.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from .auth import auth_router, get_current_user
from .routes import analysis, companies, dashboard, job_runs

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


@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/health", tags=["Health"])
def api_health_check():
    """API health check."""
    return {"status": "ok", "service": "InvestingAssistant API"}


# AWS Lambda handler via Mangum
handler = Mangum(app, lifespan="off")
