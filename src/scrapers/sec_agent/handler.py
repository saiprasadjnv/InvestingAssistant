"""
Lambda handler for the SEC EDGAR scraper agent.

Entry-point: :func:`handler`.

Flow
----
1. Receive an event with a ``companies`` key.
2. For each company, fetch recent filings from EDGAR.
3. Deduplicate against DynamoDB (skip already-processed documents).
4. Parse new filings and upload the resulting :class:`ScrapedDocument` to S3.
5. Mark each processed document in DynamoDB.
6. Return a summary of all uploaded S3 keys.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.shared.config import is_local
from src.shared.constants import SEC_FILING_TYPES_OF_INTEREST
from src.shared.models import Company, DataSource
from src.shared.storage import create_file_storage, create_dynamo_storage

from .edgar_client import EDGARClient
from .filing_parser import parse_filing

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------

async def _process_company(
    company: Company,
    client: EDGARClient,
    s3: S3Storage,
    dynamo: DynamoStorage,
) -> list[str]:
    """Process a single company: fetch, deduplicate, parse, store.

    Args:
        company: The company to process.
        client: An open :class:`EDGARClient`.
        s3: S3 storage helper.
        dynamo: DynamoDB storage helper.

    Returns:
        List of S3 keys for the newly uploaded documents.
    """
    uploaded_keys: list[str] = []

    logger.info("Processing company: %s (CIK %s)", company.ticker, company.cik)

    # 1. Fetch filing metadata -------------------------------------------------
    try:
        filings = await client.get_company_filings(
            cik=company.cik,
            form_types=SEC_FILING_TYPES_OF_INTEREST,
        )
    except Exception:
        logger.exception("Failed to fetch filings for %s", company.ticker)
        return uploaded_keys

    if not filings:
        logger.info("No filings of interest found for %s", company.ticker)
        return uploaded_keys

    # 2. Iterate filings, deduplicate, parse, store ----------------------------
    for filing in filings:
        accession_number: str = filing.get("accessionNumber", "")
        primary_document: str = filing.get("primaryDocument", "")
        form_type: str = filing.get("form", "")

        if not accession_number or not primary_document:
            logger.debug("Skipping filing with missing accession/primary doc")
            continue

        # Build a stable document ID for deduplication.
        doc_id = f"SEC_{company.ticker}_{accession_number}"

        # 2a. Check if already processed.
        if dynamo.is_document_processed("SCRAPED", doc_id):
            logger.debug("Already processed: %s — skipping", doc_id)
            continue

        # 2b. Download the filing HTML.
        try:
            filing_url = client.build_filing_url(
                company.cik, accession_number, primary_document
            )
            html_content = await client.get_filing_document(
                company.cik, accession_number, primary_document
            )
        except Exception:
            logger.exception(
                "Failed to download filing %s for %s",
                accession_number,
                company.ticker,
            )
            continue

        # 2c. Parse into a ScrapedDocument.
        try:
            document = parse_filing(
                html_content=html_content,
                ticker=company.ticker,
                filing_metadata=filing,
                filing_url=filing_url,
            )
        except Exception:
            logger.exception(
                "Failed to parse filing %s for %s",
                accession_number,
                company.ticker,
            )
            continue

        # 2d. Upload to S3.
        try:
            s3_key = s3.upload_document(document)
            uploaded_keys.append(s3_key)
            logger.info(
                "Uploaded %s %s → %s",
                form_type,
                accession_number,
                s3_key,
            )
        except Exception:
            logger.exception(
                "Failed to upload filing %s to S3 for %s",
                accession_number,
                company.ticker,
            )
            continue

        # 2e. Mark as processed in DynamoDB.
        try:
            dynamo.mark_document_processed(
                source="SCRAPED",
                doc_id=doc_id,
                metadata={
                    "ticker": company.ticker,
                    "form_type": form_type,
                    "filing_date": filing.get("filingDate", ""),
                    "s3_key": s3_key,
                },
            )
        except Exception:
            logger.exception(
                "Failed to mark filing %s as processed for %s",
                accession_number,
                company.ticker,
            )
            # Continue anyway — worst case we'll re-process next run.

    return uploaded_keys


async def _process_all_companies(companies: list[Company]) -> list[str]:
    """Process all companies through the EDGAR pipeline.

    Opens a shared :class:`EDGARClient` and iterates each company
    sequentially to respect rate limits.
    """
    s3 = create_file_storage()
    dynamo = create_dynamo_storage()

    all_keys: list[str] = []
    async with EDGARClient() as client:
        for company in companies:
            try:
                keys = await _process_company(company, client, s3, dynamo)
                all_keys.extend(keys)
            except Exception:
                logger.exception(
                    "Unhandled error processing company %s — continuing with next",
                    company.ticker,
                )

    return all_keys


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda handler for the SEC EDGAR scraper.

    Args:
        event: Must contain a ``companies`` key with a list of company
               dicts matching the :class:`Company` model.
        context: Lambda context (unused).

    Returns:
        A dict with ``statusCode``, ``scraped_count``, and ``s3_keys``.
    """
    logger.info("SEC Agent handler invoked")

    # ---- Parse input companies -------------------------------------------
    raw_companies = event.get("companies", [])
    if not raw_companies:
        logger.warning("No companies provided in event payload")
        return {
            "statusCode": 200,
            "scraped_count": 0,
            "s3_keys": [],
            "errors": [],
        }

    companies: list[Company] = []
    errors: list[str] = []
    for raw in raw_companies:
        try:
            companies.append(Company(**raw))
        except Exception as exc:
            msg = f"Invalid company payload: {raw!r} — {exc}"
            logger.error(msg)
            errors.append(msg)

    if not companies:
        return {
            "statusCode": 400,
            "scraped_count": 0,
            "s3_keys": [],
            "errors": errors,
        }

    # ---- Run the async pipeline ------------------------------------------
    # In AWS Lambda the default event loop policy works fine; locally we
    # may need to create a fresh loop.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an event loop (e.g. Jupyter, some Lambda runtimes).
        import nest_asyncio  # type: ignore[import-untyped]

        nest_asyncio.apply()
        s3_keys = loop.run_until_complete(_process_all_companies(companies))
    else:
        s3_keys = asyncio.run(_process_all_companies(companies))

    logger.info(
        "SEC Agent finished — scraped %d documents for %d companies",
        len(s3_keys),
        len(companies),
    )

    return {
        "statusCode": 200,
        "scraped_count": len(s3_keys),
        "s3_keys": s3_keys,
        "errors": errors,
    }
