"""
AWS Lambda handler for the Company Info Agent.

Entry point that orchestrates investor-page and news-page scraping for
every configured company, deduplicates documents, and persists new ones
to S3 and DynamoDB.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.config import load_companies
from src.shared.models import Company, DataSource, ScrapedDocument
from src.shared.storage import create_file_storage, create_dynamo_storage

from .investor_page_scraper import scrape_investor_page
from .news_page_scraper import scrape_news_page

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _scrape_company(company: Company) -> tuple[list[ScrapedDocument], list[ScrapedDocument]]:
    """
    Run both scrapers for a single company, returning investor docs and news docs.

    Each scraper is isolated so that a failure in one does not prevent the other
    from running.
    """
    investor_docs: list[ScrapedDocument] = []
    news_docs: list[ScrapedDocument] = []

    try:
        investor_docs = await scrape_investor_page(company)
    except Exception:
        logger.exception("Investor-page scraper failed for %s.", company.ticker)

    try:
        news_docs = await scrape_news_page(company)
    except Exception:
        logger.exception("News-page scraper failed for %s.", company.ticker)

    return investor_docs, news_docs


def _persist_documents(
    documents: list[ScrapedDocument],
    source: DataSource,
    s3,
    dynamo,
) -> list[str]:
    """
    Upload *documents* to S3 and mark them as processed in DynamoDB.

    Only documents that have **not** already been processed (according to
    DynamoDB) are uploaded.  Returns a list of S3 keys for newly stored
    documents.
    """
    uploaded_keys: list[str] = []

    for doc in documents:
        if dynamo.is_document_processed(source, doc.doc_id):
            logger.debug("Document already processed — skipping: %s", doc.doc_id)
            continue

        try:
            s3_key = s3.upload_document(doc)
            doc.s3_key = s3_key
            dynamo.mark_document_processed(
                source,
                doc.doc_id,
                metadata={
                    "ticker": doc.ticker,
                    "title": doc.title,
                    "url": doc.url,
                    "s3_key": s3_key,
                },
            )
            uploaded_keys.append(s3_key)
            logger.info("Stored new document: %s → %s", doc.doc_id, s3_key)
        except Exception:
            logger.exception("Failed to persist document %s.", doc.doc_id)

    return uploaded_keys


async def _process_all_companies(companies: list[Company]) -> dict[str, Any]:
    """
    Process every company: scrape → deduplicate → persist.

    Returns a summary dict suitable for the Lambda response.
    """
    s3 = create_file_storage()
    dynamo = create_dynamo_storage()

    all_s3_keys: list[str] = []
    companies_processed = 0
    companies_failed = 0
    total_investor_docs = 0
    total_news_docs = 0
    errors: list[str] = []

    for company in companies:
        try:
            investor_docs, news_docs = await _scrape_company(company)

            investor_keys = _persist_documents(
                investor_docs, DataSource.INVESTOR_PAGE, s3, dynamo,
            )
            news_keys = _persist_documents(
                news_docs, DataSource.NEWS_PAGE, s3, dynamo,
            )

            all_s3_keys.extend(investor_keys)
            all_s3_keys.extend(news_keys)
            total_investor_docs += len(investor_docs)
            total_news_docs += len(news_docs)
            companies_processed += 1

            logger.info(
                "%s: investor=%d (new=%d), news=%d (new=%d)",
                company.ticker,
                len(investor_docs), len(investor_keys),
                len(news_docs), len(news_keys),
            )

        except Exception as exc:
            companies_failed += 1
            error_msg = f"{company.ticker}: {exc}"
            errors.append(error_msg)
            logger.exception("Failed to process company %s.", company.ticker)

    return {
        "companies_processed": companies_processed,
        "companies_failed": companies_failed,
        "investor_docs_scraped": total_investor_docs,
        "news_docs_scraped": total_news_docs,
        "new_documents_uploaded": len(all_s3_keys),
        "s3_keys": all_s3_keys,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for the Company Info Agent.

    **Event shape** (all fields optional)::

        {
            "tickers": ["AAPL", "MSFT"],   # limit to specific companies
            "run_id": "run_abc123"          # pipeline run identifier
        }

    If ``tickers`` is omitted every company from the config is processed.

    Returns:
        A summary dict with S3 keys for all newly uploaded documents.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    run_id: str = event.get("run_id", f"company_info_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
    requested_tickers: list[str] | None = event.get("tickers")

    logger.info("Company Info Agent starting — run_id=%s", run_id)

    # Load companies.
    companies = load_companies()
    if requested_tickers:
        ticker_set = {t.upper() for t in requested_tickers}
        companies = [c for c in companies if c.ticker.upper() in ticker_set]

    if not companies:
        logger.warning("No companies to process.")
        return {
            "statusCode": 200,
            "run_id": run_id,
            "body": {
                "companies_processed": 0,
                "new_documents_uploaded": 0,
                "s3_keys": [],
            },
        }

    logger.info("Processing %d companies.", len(companies))

    # Run the async pipeline inside the synchronous Lambda entry point.
    result = asyncio.run(
        _process_all_companies(companies),
    )

    logger.info(
        "Company Info Agent finished — processed=%d, new_docs=%d, errors=%d",
        result["companies_processed"],
        result["new_documents_uploaded"],
        len(result["errors"]),
    )

    return {
        "statusCode": 200,
        "run_id": run_id,
        "body": result,
    }
