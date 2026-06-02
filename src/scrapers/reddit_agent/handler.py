"""
AWS Lambda handler for the Reddit Agent scraper.

Entry-point: ``handler(event, context)``

Workflow per company:
1. Search Reddit via :class:`RedditClient` for qualifying discussions.
2. Deduplicate against DynamoDB (``is_document_processed``).
3. Build a :class:`ScrapedDocument` with :class:`RedditPostMetadata`.
4. Upload the document to S3 via :class:`S3Storage`.
5. Mark the document as processed in DynamoDB.
6. Return a summary of all newly ingested S3 keys.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.shared.config import load_companies
from src.shared.constants import LLM_MAX_INPUT_TOKENS
from src.shared.models import (
    Company,
    DataSource,
    RedditPostMetadata,
    ScrapedDocument,
)
from src.shared.storage import create_file_storage, create_dynamo_storage

from .reddit_client import RedditClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _build_content(post: dict[str, Any]) -> str:
    """
    Assemble the textual content of a Reddit post for downstream LLM
    analysis.  Includes the title, self-text, and top comment bodies,
    truncated to roughly ``LLM_MAX_INPUT_TOKENS`` characters (≈ 1 char
    per token as a safe heuristic for English text).

    Args:
        post: A dict returned by
              :meth:`RedditClient.search_company_discussions`.

    Returns:
        A combined content string suitable for storage and analysis.
    """
    parts: list[str] = [
        f"Title: {post['title']}",
        "",
        post.get("selftext", ""),
        "",
        "--- Top Comments ---",
    ]
    for comment in post.get("top_comments", []):
        parts.append(f"[score {comment['score']}] {comment['body']}")
        parts.append("")

    combined = "\n".join(parts)
    # Rough token-limit guard
    max_chars = LLM_MAX_INPUT_TOKENS * 4  # ~4 chars per token
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n… [truncated]"
    return combined


def _process_company(
    company: Company,
    reddit_client: RedditClient,
    s3: S3Storage,
    dynamo: DynamoStorage,
) -> list[str]:
    """
    Search, deduplicate, store, and track Reddit posts for *one*
    company.

    Args:
        company: The company to search for.
        reddit_client: An initialised :class:`RedditClient`.
        s3: S3 storage helper.
        dynamo: DynamoDB storage helper.

    Returns:
        List of S3 keys for newly ingested documents.
    """
    new_keys: list[str] = []

    posts = reddit_client.search_company_discussions(
        ticker=company.ticker,
        company_name=company.name,
    )

    for post in posts:
        post_id: str = post["post_id"]
        doc_id = f"reddit_{company.ticker}_{post_id}"

        # --- Deduplication ---
        if dynamo.is_document_processed(DataSource.REDDIT, doc_id):
            logger.info("Skipping already-processed post %s", doc_id)
            continue

        # --- Build ScrapedDocument ---
        content = _build_content(post)
        permalink = post["permalink"]
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink

        metadata = RedditPostMetadata(
            post_id=post_id,
            subreddit=post["subreddit"],
            score=post["score"],
            num_comments=post["num_comments"],
            author=post["author"],
            permalink=permalink,
            top_comments=post.get("top_comments", []),
        )

        doc = ScrapedDocument(
            doc_id=doc_id,
            source=DataSource.REDDIT,
            ticker=company.ticker,
            title=post["title"],
            content=content,
            url=url,
            metadata=metadata.model_dump(),
            scraped_at=datetime.fromtimestamp(
                post["created_utc"], tz=timezone.utc
            ),
        )

        # --- Upload to S3 ---
        try:
            s3_key = s3.upload_document(doc)
            doc.s3_key = s3_key
            new_keys.append(s3_key)
            logger.info("Uploaded %s → s3://%s", doc_id, s3_key)
        except Exception:
            logger.exception("Failed to upload %s to S3", doc_id)
            continue

        # --- Mark as processed ---
        try:
            dynamo.mark_document_processed(
                source=DataSource.REDDIT,
                doc_id=doc_id,
                metadata={
                    "ticker": company.ticker,
                    "subreddit": post["subreddit"],
                    "score": post["score"],
                    "s3_key": s3_key,
                },
            )
        except Exception:
            logger.exception("Failed to mark %s as processed", doc_id)

    return new_keys


# -----------------------------------------------------------------------
# Lambda entry-point
# -----------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for the Reddit scraper agent.

    **Event schema** (supplied by the orchestrator / Step Functions):

    .. code-block:: json

        {
            "companies": [
                {"name": "Apple Inc.", "ticker": "AAPL", "sector": "Technology", "cik": "320193"}
            ]
        }

    If ``companies`` is omitted the handler falls back to
    :func:`load_companies` to use the full tracked list.

    Args:
        event: Lambda invocation event.
        context: Lambda runtime context (unused).

    Returns:
        A dict summarising the run::

            {
                "status": "completed",
                "new_documents": ["reddit/AAPL/2026-06-01/reddit_AAPL_abc123.json", …],
                "companies_processed": 5,
                "errors": ["TSLA: some error"]
            }
    """
    logger.info("Reddit scraper handler invoked — event keys: %s", list(event.keys()))

    # --- Resolve companies ---
    raw_companies = event.get("companies", [])
    if raw_companies:
        companies = [Company(**c) for c in raw_companies]
    else:
        companies = load_companies()

    logger.info("Processing %d companies", len(companies))

    # --- Initialise clients once ---
    reddit_client = RedditClient()
    s3 = create_file_storage()
    dynamo = create_dynamo_storage()

    all_new_keys: list[str] = []
    errors: list[str] = []

    for company in companies:
        try:
            keys = _process_company(company, reddit_client, s3, dynamo)
            all_new_keys.extend(keys)
            logger.info(
                "%s: %d new documents ingested", company.ticker, len(keys)
            )
        except Exception as exc:
            error_msg = f"{company.ticker}: {exc}"
            logger.exception("Error processing %s", company.ticker)
            errors.append(error_msg)

    result = {
        "status": "completed",
        "new_documents": all_new_keys,
        "companies_processed": len(companies),
        "documents_ingested": len(all_new_keys),
        "errors": errors,
    }
    logger.info("Reddit scraper finished — %s", result)
    return result
