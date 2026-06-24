"""
Lambda handler for the X/Twitter scraper agent.

Entry point: ``handler(event, context)``

For every tracked company the handler:
1. Searches X for recent high-influence tweets via :class:`XClient`.
2. Deduplicates against previously processed documents in DynamoDB.
3. Creates :class:`ScrapedDocument` instances with :class:`TweetMetadata`.
4. Uploads raw documents to S3.
5. Marks each document as processed in DynamoDB.

Returns a summary dict with S3 keys and API cost metrics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.shared.config import load_companies
from src.shared.constants import X_TOP_TWEETS_PER_COMPANY
from src.shared.models import (
    Company,
    DataSource,
    ScrapedDocument,
    TweetMetadata,
)
from src.shared.storage import create_file_storage, create_dynamo_storage

from .x_client import XClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda entry-point for the X/Twitter scraper agent.

    Args:
        event:   Lambda event payload (unused for scheduled runs).
        context: Lambda context object.

    Returns:
        A dict containing::

            {
                "source": "X",
                "companies_processed": int,
                "documents_stored": int,
                "s3_keys": [str, ...],
                "api_read_count": int,
                "errors": [str, ...],
            }
    """
    logger.info("X agent handler invoked")

    # Accept companies from Step Functions event (preferred) or load from config
    raw_companies = event.get("companies", [])
    if raw_companies:
        companies = []
        for raw in raw_companies:
            try:
                companies.append(Company(**raw) if isinstance(raw, dict) else raw)
            except Exception:
                logger.warning("Skipping invalid company: %s", raw)
        logger.info("Using %d companies from event input.", len(companies))
    else:
        companies = load_companies()
    x_client = XClient()
    s3 = create_file_storage()
    dynamo = create_dynamo_storage()

    s3_keys: list[str] = []
    errors: list[str] = []
    total_stored = 0
    companies_ok = 0

    for company in companies:
        try:
            stored = _process_company(
                company=company,
                x_client=x_client,
                s3=s3,
                dynamo=dynamo,
            )
            s3_keys.extend(stored)
            total_stored += len(stored)
            companies_ok += 1
        except Exception as exc:
            msg = f"Error processing {company.ticker}: {exc}"
            logger.exception(msg)
            errors.append(msg)

    summary = {
        "source": "X",
        "companies_processed": companies_ok,
        "documents_stored": total_stored,
        "s3_keys": s3_keys,
        "api_read_count": x_client.api_read_count,
        "errors": errors,
    }
    logger.info("X agent complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Per-company processing
# ---------------------------------------------------------------------------


def _process_company(
    company: Company,
    x_client: XClient,
    s3: S3Storage,
    dynamo: DynamoStorage,
) -> list[str]:
    """
    Search, deduplicate, store, and mark tweets for a single company.

    Args:
        company:  The company to search for.
        x_client: Pre-initialised X API client.
        s3:       S3 storage helper.
        dynamo:   DynamoDB storage helper.

    Returns:
        List of S3 keys where new documents were stored.
    """
    ticker = company.ticker
    logger.info("Processing company %s (%s)", company.name, ticker)

    tweets = x_client.search_company_tweets(
        ticker=ticker,
        company_name=company.name,
        limit=X_TOP_TWEETS_PER_COMPANY,
    )

    if not tweets:
        logger.info("No qualifying tweets for %s", ticker)
        return []

    stored_keys: list[str] = []
    seen_tweet_ids: set[str] = set()

    for tweet in tweets:
        tweet_id = tweet["tweet_id"]

        # --- Deduplicate within this batch ---
        if tweet_id in seen_tweet_ids:
            continue
        seen_tweet_ids.add(tweet_id)

        doc_id = f"x_{ticker}_{tweet_id}"

        # --- Deduplicate against DynamoDB ---
        if dynamo.is_document_processed(DataSource.X, doc_id):
            logger.debug("Skipping already-processed tweet %s", doc_id)
            continue

        # --- Build metadata ---
        tweet_meta = TweetMetadata(
            tweet_id=tweet_id,
            author_id=tweet["author_id"],
            author_username=tweet["author_username"],
            author_followers=tweet["followers_count"],
            retweet_count=tweet["retweet_count"],
            like_count=tweet["like_count"],
            reply_count=tweet["reply_count"],
        )

        tweet_url = f"https://x.com/{tweet['author_username']}/status/{tweet_id}"

        doc = ScrapedDocument(
            doc_id=doc_id,
            source=DataSource.X,
            ticker=ticker,
            title=f"Tweet by @{tweet['author_username']} about ${ticker}",
            content=tweet["text"],
            url=tweet_url,
            metadata=tweet_meta.model_dump(),
            scraped_at=datetime.utcnow(),
        )

        # --- Upload to S3 ---
        s3_key = s3.upload_document(doc)
        stored_keys.append(s3_key)

        # --- Mark as processed ---
        dynamo.mark_document_processed(
            source=DataSource.X,
            doc_id=doc_id,
            metadata={
                "ticker": ticker,
                "tweet_id": tweet_id,
                "author": tweet["author_username"],
                "s3_key": s3_key,
            },
        )

        logger.info(
            "Stored tweet %s by @%s → %s",
            tweet_id,
            tweet["author_username"],
            s3_key,
        )

    return stored_keys
