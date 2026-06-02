#!/usr/bin/env python3
"""
Local development runner for the InvestingAssistant pipeline.

Runs the full scrape → analyze → score pipeline locally for testing
without requiring AWS infrastructure. Uses local file storage as
a fallback when S3/DynamoDB are unavailable.

Usage:
    python scripts/local_run.py                    # Run all companies
    python scripts/local_run.py --ticker NVDA      # Run single company
    python scripts/local_run.py --source SEC       # Run single source
    python scripts/local_run.py --dry-run          # Scrape only, no LLM
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

os.environ.setdefault("INVESTING_ASSISTANT_ENV", "local")

from src.shared.config import load_companies
from src.shared.models import Company, DataSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("local_run")


def run_sec_agent(companies: list[Company]) -> list[str]:
    """Run SEC agent locally."""
    logger.info("=== SEC Agent ===")
    try:
        from src.scrapers.sec_agent.handler import handler
        event = {"companies": [c.model_dump() for c in companies]}
        result = handler(event, None)
        keys = result.get("s3_keys", [])
        logger.info("SEC Agent result: %d documents scraped", len(keys))
        return keys
    except Exception as exc:
        logger.error("SEC Agent failed: %s", exc, exc_info=True)
        return []


def run_company_info_agent(companies: list[Company]) -> list[str]:
    """Run Company Info agent locally."""
    logger.info("=== Company Info Agent ===")
    try:
        from src.scrapers.company_info_agent.handler import handler
        event = {"companies": [c.model_dump() for c in companies]}
        result = handler(event, None)
        body = result.get("body", {})
        keys = body.get("s3_keys", []) if isinstance(body, dict) else []
        logger.info("Company Info Agent result: %d documents", len(keys))
        return keys
    except Exception as exc:
        logger.error("Company Info Agent failed: %s", exc, exc_info=True)
        return []


def run_reddit_agent(companies: list[Company]) -> list[str]:
    """Run Reddit agent locally."""
    logger.info("=== Reddit Agent ===")
    try:
        from src.scrapers.reddit_agent.handler import handler
        event = {"companies": [c.model_dump() for c in companies]}
        result = handler(event, None)
        keys = result.get("new_documents", [])
        logger.info("Reddit Agent result: %d documents", len(keys))
        return keys
    except Exception as exc:
        logger.error("Reddit Agent failed: %s", exc, exc_info=True)
        return []


def run_x_agent(companies: list[Company]) -> list[str]:
    """Run X/Twitter agent locally."""
    logger.info("=== X Agent ===")
    try:
        from src.scrapers.x_agent.handler import handler
        event = {"companies": [c.model_dump() for c in companies]}
        result = handler(event, None)
        keys = result.get("s3_keys", [])
        logger.info("X Agent result: %d documents", len(keys))
        return keys
    except Exception as exc:
        logger.error("X Agent failed: %s", exc, exc_info=True)
        return []


def run_sentiment_analyzer(s3_keys: list[str]) -> dict:
    """Run sentiment analyzer locally."""
    logger.info("=== Sentiment Analyzer (%d documents) ===", len(s3_keys))
    if not s3_keys:
        logger.info("No documents to analyze")
        return {"result_ids": []}
    try:
        from src.analyzers.sentiment_analyzer.handler import handler
        event = {"s3_keys": s3_keys}
        result = handler(event, None)
        logger.info("Sentiment Analyzer: %d processed", result.get("documents_processed", 0))
        return result
    except Exception as exc:
        logger.error("Sentiment Analyzer failed: %s", exc, exc_info=True)
        return {"result_ids": []}


def run_impact_scorer(result_ids: list[str]) -> dict:
    """Run impact scorer locally."""
    logger.info("=== Impact Scorer (%d results) ===", len(result_ids))
    if not result_ids:
        logger.info("No results to score")
        return {}
    try:
        from src.analyzers.impact_scorer.handler import handler
        event = {"result_ids": result_ids}
        result = handler(event, None)
        logger.info(
            "Impact Scorer: %d scored, %d alerts",
            result.get("scored_count", 0),
            result.get("alerts_triggered", 0),
        )
        return result
    except Exception as exc:
        logger.error("Impact Scorer failed: %s", exc, exc_info=True)
        return {}


def main():
    parser = argparse.ArgumentParser(description="Run InvestingAssistant pipeline locally")
    parser.add_argument("--ticker", type=str, help="Run for a single ticker only")
    parser.add_argument("--source", type=str, choices=["SEC", "COMPANY", "REDDIT", "X", "ALL"],
                        default="ALL", help="Run specific source only")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, skip LLM analysis")
    args = parser.parse_args()

    run_id = f"local-{uuid4().hex[:8]}"
    logger.info("=" * 60)
    logger.info("InvestingAssistant Local Pipeline Run: %s", run_id)
    logger.info("=" * 60)

    # Load companies
    companies = load_companies()
    if args.ticker:
        companies = [c for c in companies if c.ticker.upper() == args.ticker.upper()]
        if not companies:
            logger.error("Ticker %s not found in config", args.ticker)
            sys.exit(1)

    logger.info("Processing %d companies: %s", len(companies), [c.ticker for c in companies])

    # Run scrapers
    all_s3_keys: list[str] = []
    started = datetime.now(timezone.utc)

    if args.source in ("SEC", "ALL"):
        keys = run_sec_agent(companies)
        all_s3_keys.extend([k.get("s3_key", k) if isinstance(k, dict) else k for k in keys])

    if args.source in ("COMPANY", "ALL"):
        keys = run_company_info_agent(companies)
        all_s3_keys.extend([k.get("s3_key", k) if isinstance(k, dict) else k for k in keys])

    if args.source in ("REDDIT", "ALL"):
        keys = run_reddit_agent(companies)
        all_s3_keys.extend([k.get("s3_key", k) if isinstance(k, dict) else k for k in keys])

    if args.source in ("X", "ALL"):
        keys = run_x_agent(companies)
        all_s3_keys.extend([k.get("s3_key", k) if isinstance(k, dict) else k for k in keys])

    logger.info("Total documents scraped: %d", len(all_s3_keys))

    if args.dry_run:
        logger.info("Dry run — skipping LLM analysis")
    elif all_s3_keys:
        # Run analyzers
        sentiment_result = run_sentiment_analyzer(all_s3_keys)
        result_ids = sentiment_result.get("result_ids", [])

        if result_ids:
            run_impact_scorer(result_ids)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("=" * 60)
    logger.info("Pipeline run %s completed in %.1fs", run_id, elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
