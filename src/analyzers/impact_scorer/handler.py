"""
Impact Scorer Lambda handler.

Receives analysis results from the Sentiment Analyzer, computes
composite impact scores with corroboration bonuses, updates DynamoDB,
and triggers SNS notifications for high-confidence findings.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.shared.models import AnalysisResult, DataSource, ImpactDirection, Sentiment
from src.shared.storage import create_dynamo_storage

from .scoring_engine import ImpactScorer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SNS_TOPIC_ARN = os.environ.get("SNS_ALERT_TOPIC_ARN", "")


def _send_alert(result: dict, final_score: float) -> None:
    """Publish a high-confidence finding to the SNS alert topic."""
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_ALERT_TOPIC_ARN not set; skipping alert")
        return

    try:
        sns = boto3.client("sns")
        message = (
            f"🚨 High-Confidence Finding for {result.get('ticker', 'N/A')}\n\n"
            f"Source: {result.get('source', 'N/A')}\n"
            f"Sentiment: {result.get('sentiment', 'N/A')}\n"
            f"Impact Direction: {result.get('impact_direction', 'N/A')}\n"
            f"Impact Score: {final_score:.2f}\n"
            f"Summary: {result.get('summary', 'No summary')}\n"
            f"Key Factors: {', '.join(result.get('key_factors', []))}\n"
            f"Source URL: {result.get('source_url', 'N/A')}"
        )
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"⚡ {result.get('ticker', '')} — {result.get('impact_direction', '')} Signal (Score: {final_score:.2f})",
            Message=message,
        )
        logger.info("SNS alert sent for %s (score=%.2f)", result.get("ticker"), final_score)
    except ClientError as exc:
        logger.error("Failed to send SNS alert: %s", exc)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point for the Impact Scorer.

    Parameters
    ----------
    event : dict
        Expected keys:
        - ``result_ids`` (list[str]): Analysis result IDs from sentiment analyzer.
        - ``tickers`` (list[str], optional): Ticker symbols to re-score.
    context :
        Lambda context (unused).

    Returns
    -------
    dict
        Summary with ``scored_count``, ``alerts_triggered``, and ``errors``.
    """
    result_ids = event.get("result_ids", [])
    tickers = event.get("tickers", [])

    logger.info(
        "Impact Scorer invoked: %d result_ids, %d tickers",
        len(result_ids),
        len(tickers),
    )

    dynamo = create_dynamo_storage()
    scorer = ImpactScorer()

    scored_count = 0
    alerts_triggered = 0
    errors: list[str] = []

    # Collect items to score: either by explicit result_ids or by ticker query
    items_to_score: list[dict] = []

    if result_ids:
        # If we got explicit result IDs, query each ticker for recent results
        # (result_ids come from the sentiment analyzer output)
        seen_tickers: set[str] = set()
        for rid in result_ids:
            # result_id format: {ticker}_{source}_{hash}
            parts = rid.split("_", 2)
            if parts:
                seen_tickers.add(parts[0])

        for ticker in seen_tickers:
            try:
                items = dynamo.get_analyses_for_ticker(ticker, limit=10)
                items_to_score.extend(items)
            except Exception as exc:
                errors.append(f"Failed to fetch analyses for {ticker}: {exc}")

    elif tickers:
        for ticker in tickers:
            try:
                items = dynamo.get_analyses_for_ticker(ticker, limit=20)
                items_to_score.extend(items)
            except Exception as exc:
                errors.append(f"Failed to fetch analyses for {ticker}: {exc}")

    # Score each item
    for item in items_to_score:
        try:
            ticker = item.get("ticker", "")
            source = DataSource(item.get("source", "SEC"))
            direction = ImpactDirection(item.get("impact_direction", "NEUTRAL"))

            # Build a lightweight AnalysisResult for scoring
            result_obj = AnalysisResult(
                result_id=item.get("result_id", ""),
                ticker=ticker,
                company_name=item.get("company_name", ticker),
                source=source,
                sentiment=Sentiment(item.get("sentiment", "NEUTRAL")),
                sentiment_confidence=float(item.get("sentiment_confidence", 0.0)),
                impact_score=float(item.get("impact_score", 0.0)),
                impact_direction=direction,
                summary=item.get("summary", ""),
                key_factors=item.get("key_factors", []),
                raw_s3_path=item.get("raw_s3_path", ""),
                source_url=item.get("source_url", ""),
                source_title=item.get("source_title", ""),
            )

            # Compute composite score
            base_score = scorer.compute_composite_score(result_obj)
            corroboration_bonus = scorer.check_corroboration(
                ticker, direction, dynamo
            )
            final_score = min(1.0, base_score + corroboration_bonus)

            # Update the item in DynamoDB with the final score
            result_obj.impact_score = final_score
            dynamo.put_analysis_result(result_obj)
            scored_count += 1

            # Check alert threshold
            if scorer.should_alert(final_score):
                alerts_triggered += 1
                _send_alert(item, final_score)

        except Exception as exc:
            error_msg = f"Error scoring {item.get('result_id', '?')}: {exc}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)

    summary = {
        "status": "completed",
        "scored_count": scored_count,
        "alerts_triggered": alerts_triggered,
        "errors": errors,
    }

    logger.info(
        "Impact scoring complete: %d scored, %d alerts, %d errors",
        scored_count,
        alerts_triggered,
        len(errors),
    )
    return summary
