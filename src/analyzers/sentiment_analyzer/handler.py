"""
Sentiment Analyzer Lambda handler.

Entry point: ``handler(event, context)``

Workflow
--------
1. Receive a list of S3 keys pointing to :class:`ScrapedDocument` objects.
2. For each document:
   a. Download from S3.
   b. Select the appropriate prompt template based on the document source.
   c. Call the LLM via :class:`LLMClient`.
   d. Parse the JSON response.
   e. Build an :class:`AnalysisResult`.
   f. Store the result in DynamoDB.
3. Return a summary with analysis-result IDs and aggregated LLM metrics.

Error isolation: a single document's failure is logged but does **not**
prevent the remaining documents from being processed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from src.shared.config import get_company_by_ticker
from src.shared.models import (
    AnalysisResult,
    DataSource,
    ImpactDirection,
    LLMCallMetrics,
    ScrapedDocument,
    Sentiment,
)
from src.shared.storage import create_file_storage, create_dynamo_storage

from .llm_client import LLMClient
from .prompts import PROMPT_TEMPLATE_BY_SOURCE, SYSTEM_PROMPT

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_result_id(ticker: str, source: DataSource) -> str:
    """Generate a unique result ID: ``{ticker}_{source}_{timestamp_hash}``."""
    ts = datetime.now(timezone.utc).isoformat()
    short_hash = hashlib.sha256(ts.encode()).hexdigest()[:8]
    return f"{ticker}_{source.value}_{short_hash}"


def _parse_llm_response(raw_text: str) -> dict[str, Any]:
    """Parse the LLM JSON response, gracefully handling edge cases.

    The LLM is instructed to return bare JSON, but some models may wrap
    it in markdown code fences or return truncated output.  This parser
    applies several fallback strategies before giving up:

    1. Strip markdown code fences and try ``json.loads``.
    2. Regex-extract a JSON object and try ``json.loads``.
    3. Attempt to repair truncated JSON (add missing closing tokens).
    4. Extract individual fields via regex as a last resort.
    """
    text = raw_text.strip()

    # --- Step 1: Strip markdown code fences if present -----------------
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # --- Step 2: Direct parse ------------------------------------------
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Direct json.loads failed; trying regex extraction.")

    # --- Step 3: Regex – nested JSON object ----------------------------
    nested_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}')
    match = nested_pattern.search(text)
    if match:
        try:
            data = json.loads(match.group())
            logger.info("Parsed LLM response via nested-object regex.")
            return data
        except json.JSONDecodeError:
            logger.debug("Nested-object regex match was not valid JSON.")

    # --- Step 4: Regex – greedy match (allows deeply nested) -----------
    greedy_match = re.search(r'\{.*\}', text, re.DOTALL)
    if greedy_match:
        try:
            data = json.loads(greedy_match.group())
            logger.info("Parsed LLM response via greedy regex.")
            return data
        except json.JSONDecodeError:
            logger.debug("Greedy regex match was not valid JSON.")

    # --- Step 5: Repair truncated JSON ---------------------------------
    candidate = greedy_match.group() if greedy_match else text
    repaired = _try_repair_json(candidate)
    if repaired is not None:
        logger.info("Parsed LLM response after repairing truncated JSON.")
        return repaired

    # --- Step 6: Extract individual fields as last resort ---------------
    logger.warning(
        "All JSON parsing strategies failed; extracting fields via regex. "
        "raw=%s",
        raw_text[:300],
    )
    return _extract_fields_by_regex(text)


def _try_repair_json(text: str) -> dict[str, Any] | None:
    """Try to fix truncated JSON by appending missing closing tokens."""
    # Count unbalanced braces / brackets
    for extra in ('', ']', '}', ']}', '"]}', '"}', '"]}'  ):
        try:
            return json.loads(text + extra)
        except json.JSONDecodeError:
            continue
    return None


def _extract_fields_by_regex(text: str) -> dict[str, Any]:
    """Pull individual fields out of malformed LLM output via regex."""
    defaults: dict[str, Any] = {
        "sentiment": "NEUTRAL",
        "sentiment_confidence": 0.0,
        "impact_direction": "NEUTRAL",
        "impact_magnitude": 0.0,
        "summary": "LLM response could not be parsed.",
        "key_factors": [],
    }

    # String fields
    for field in ("sentiment", "impact_direction", "summary"):
        m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', text)
        if m:
            defaults[field] = m.group(1)

    # Float fields
    for field in ("sentiment_confidence", "impact_magnitude"):
        m = re.search(rf'"{field}"\s*:\s*([\d.]+)', text)
        if m:
            try:
                defaults[field] = float(m.group(1))
            except ValueError:
                pass

    # key_factors (list of strings)
    m = re.search(r'"key_factors"\s*:\s*\[([^\]]*)', text)
    if m:
        factors = re.findall(r'"([^"]+)"', m.group(1))
        if factors:
            defaults["key_factors"] = factors

    return defaults


def _coerce_sentiment(value: str) -> Sentiment:
    """Map raw string to ``Sentiment`` enum, defaulting to ``NEUTRAL``."""
    try:
        return Sentiment(value.upper())
    except (ValueError, AttributeError):
        return Sentiment.NEUTRAL


def _coerce_direction(value: str) -> ImpactDirection:
    """Map raw string to ``ImpactDirection`` enum, defaulting to ``NEUTRAL``."""
    try:
        return ImpactDirection(value.upper())
    except (ValueError, AttributeError):
        return ImpactDirection.NEUTRAL


def _is_complex_filing(doc: ScrapedDocument) -> bool:
    """Heuristic: use the deep-analysis model for major SEC filings."""
    if doc.source != DataSource.SEC:
        return False
    form_type = doc.metadata.get("form_type", "")
    return form_type in ("10-K", "10-Q")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

async def _process_document(
    doc: ScrapedDocument,
    llm: LLMClient,
    storage: DynamoStorage,
) -> tuple[str | None, LLMCallMetrics | None]:
    """Analyse a single scraped document and persist the result.

    Returns ``(result_id, llm_metrics)`` on success, or
    ``(None, None)`` if the document could not be processed.
    """
    # 1. Select prompt template
    template = PROMPT_TEMPLATE_BY_SOURCE.get(doc.source)
    if template is None:
        logger.warning("No prompt template for source %s; skipping doc %s", doc.source, doc.doc_id)
        return None, None

    # 2. Look up company details for richer prompts
    company = get_company_by_ticker(doc.ticker)
    company_name = company.name if company else doc.ticker

    # 3. Build the prompt
    prompt = template.format(
        company_name=company_name,
        ticker=doc.ticker,
        content=doc.content,
        source_metadata=json.dumps(doc.metadata, default=str),
    )

    # 4. Call LLM (deep model for complex filings)
    if _is_complex_filing(doc):
        response_text, metrics = await llm.analyze_deep(prompt, SYSTEM_PROMPT)
    else:
        response_text, metrics = await llm.analyze(prompt, SYSTEM_PROMPT)

    # 5. Parse response
    parsed = _parse_llm_response(response_text)

    # 6. Build AnalysisResult
    result_id = _build_result_id(doc.ticker, doc.source)
    result = AnalysisResult(
        result_id=result_id,
        ticker=doc.ticker,
        company_name=company_name,
        source=doc.source,
        sentiment=_coerce_sentiment(parsed.get("sentiment", "NEUTRAL")),
        sentiment_confidence=float(parsed.get("sentiment_confidence", 0.0)),
        impact_score=float(parsed.get("impact_magnitude", 0.0)),
        impact_direction=_coerce_direction(parsed.get("impact_direction", "NEUTRAL")),
        summary=parsed.get("summary", ""),
        key_factors=parsed.get("key_factors", []),
        raw_s3_path=doc.s3_key,
        source_url=doc.url,
        source_title=doc.title,
        llm_model=metrics.model,
        llm_tokens_in=metrics.tokens_in,
        llm_tokens_out=metrics.tokens_out,
    )

    # 7. Store
    storage.put_analysis_result(result)
    storage.mark_document_processed(doc.source, doc.doc_id, {"result_id": result_id})

    logger.info(
        "Analysed doc %s → result %s (sentiment=%s, impact=%.2f)",
        doc.doc_id,
        result_id,
        result.sentiment.value,
        result.impact_score,
    )
    return result_id, metrics


async def _process_all(
    s3_keys: list[str],
    s3: S3Storage,
    dynamo: DynamoStorage,
    llm: LLMClient,
) -> dict[str, Any]:
    """Process all documents and return a summary dict."""
    result_ids: list[str] = []
    all_metrics: list[dict] = []
    errors: list[str] = []

    for s3_key in s3_keys:
        try:
            doc = s3.download_document(s3_key)

            # Skip if already processed
            if dynamo.is_document_processed(doc.source, doc.doc_id):
                logger.info("Document %s already processed; skipping", doc.doc_id)
                continue

            result_id, metrics = await _process_document(doc, llm, dynamo)
            if result_id and metrics:
                result_ids.append(result_id)
                all_metrics.append(metrics.model_dump())

        except Exception as exc:
            error_msg = f"Error processing {s3_key}: {exc}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)

    return {
        "result_ids": result_ids,
        "documents_processed": len(result_ids),
        "documents_skipped": len(s3_keys) - len(result_ids) - len(errors),
        "errors": errors,
        "llm_metrics": all_metrics,
    }


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point for the Sentiment Analyzer.

    Parameters
    ----------
    event : dict
        Expected keys:
        - ``s3_keys`` (list[str]): S3 keys of :class:`ScrapedDocument` objects.
        - ``primary_provider`` (str, optional): LLM provider override.
    context :
        Lambda context (unused).

    Returns
    -------
    dict
        Summary with ``result_ids``, ``documents_processed``, ``errors``,
        and ``llm_metrics``.
    """
    logger.info("Sentiment Analyzer handler invoked with %d document(s)", len(event.get("s3_keys", [])))

    s3_keys: list[str] = event.get("s3_keys", [])
    if not s3_keys:
        logger.warning("No S3 keys provided; nothing to do.")
        return {
            "result_ids": [],
            "documents_processed": 0,
            "documents_skipped": 0,
            "errors": [],
            "llm_metrics": [],
        }

    primary_provider = event.get("primary_provider", "gemini")

    # Initialise clients
    s3_storage = create_file_storage()
    dynamo_storage = create_dynamo_storage()
    llm_client = LLMClient(primary_provider=primary_provider)

    # Run the async processing loop
    summary = asyncio.run(
        _process_all(s3_keys, s3_storage, dynamo_storage, llm_client)
    )

    logger.info(
        "Sentiment analysis complete: %d processed, %d errors",
        summary["documents_processed"],
        len(summary["errors"]),
    )
    return summary
