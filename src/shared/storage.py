"""
Storage helpers for S3 and DynamoDB operations.

Provides unified interfaces for storing raw scraped documents in S3
and structured analysis results in DynamoDB.

For local development without AWS, set INVESTING_ASSISTANT_ENV=local
to use file-based storage under .local_data/
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from .config import get_dynamodb_table_name, get_s3_bucket_name, is_local
from .models import AnalysisResult, DataSource, JobRunMetrics, ScrapedDocument

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Timezone-aware UTC now (avoids deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


def _get_aws_region() -> str:
    """Get AWS region from env, defaulting to us-east-1."""
    return os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


# ---------------------------------------------------------------------------
# Decimal helper for DynamoDB (floats are not supported)
# ---------------------------------------------------------------------------

def _float_to_decimal(obj: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _decimal_to_float(obj: Any) -> Any:
    """Recursively convert Decimals back to floats when reading from DynamoDB."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# S3 Storage
# ---------------------------------------------------------------------------

class S3Storage:
    """
    Manages raw document storage in S3 with organized key structure:
      {source}/{ticker}/{date}/{filename}.json
    """

    def __init__(self, bucket_name: Optional[str] = None):
        import boto3
        self.bucket_name = bucket_name or get_s3_bucket_name()
        self._client = boto3.client("s3", region_name=_get_aws_region())

    def _build_key(self, source: DataSource, ticker: str, doc_id: str) -> str:
        """Build an S3 key with organized structure."""
        date_str = _utcnow().strftime("%Y-%m-%d")
        source_prefix = {
            DataSource.SEC: "sec-filings",
            DataSource.INVESTOR_PAGE: "investor-page",
            DataSource.NEWS_PAGE: "news-page",
            DataSource.REDDIT: "reddit",
            DataSource.X: "x-twitter",
        }.get(source, "other")

        return f"{source_prefix}/{ticker}/{date_str}/{doc_id}.json"

    def upload_document(self, document: ScrapedDocument) -> str:
        """
        Upload a scraped document to S3.

        Args:
            document: The ScrapedDocument to store.

        Returns:
            The S3 key where the document was stored.
        """
        s3_key = self._build_key(document.source, document.ticker, document.doc_id)

        payload = document.model_dump(mode="json")

        try:
            self._client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=json.dumps(payload, default=str),
                ContentType="application/json",
            )
            logger.info(f"Uploaded document to s3://{self.bucket_name}/{s3_key}")
            return s3_key
        except ClientError as e:
            logger.error(f"Failed to upload to S3: {e}")
            raise

    def download_document(self, s3_key: str) -> ScrapedDocument:
        """Download and deserialize a ScrapedDocument from S3."""
        try:
            response = self._client.get_object(
                Bucket=self.bucket_name,
                Key=s3_key,
            )
            data = json.loads(response["Body"].read().decode("utf-8"))
            return ScrapedDocument(**data)
        except ClientError as e:
            logger.error(f"Failed to download from S3: {e}")
            raise

    def list_documents(
        self, source: DataSource, ticker: str, date_str: Optional[str] = None
    ) -> list[str]:
        """List S3 keys for a given source and ticker, optionally filtered by date."""
        source_prefix = {
            DataSource.SEC: "sec-filings",
            DataSource.INVESTOR_PAGE: "investor-page",
            DataSource.NEWS_PAGE: "news-page",
            DataSource.REDDIT: "reddit",
            DataSource.X: "x-twitter",
        }.get(source, "other")

        prefix = f"{source_prefix}/{ticker}/"
        if date_str:
            prefix += f"{date_str}/"

        keys = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        except ClientError as e:
            logger.error(f"Failed to list S3 objects: {e}")
            raise

        return keys


# ---------------------------------------------------------------------------
# DynamoDB Storage
# ---------------------------------------------------------------------------

class DynamoStorage:
    """
    Manages structured data in DynamoDB tables:
    - AnalysisResults: PK=TICKER#{ticker}, SK=ANALYSIS#{timestamp}#{source}
    - ProcessedDocuments: PK=SOURCE#{source}, SK=DOC#{doc_id}
    - JobRuns: PK=RUN#{run_id}, SK=METRIC#{metric}
    """

    def __init__(self):
        import boto3
        self._resource = boto3.resource("dynamodb", region_name=_get_aws_region())
        self._analysis_table = self._resource.Table(get_dynamodb_table_name("analysis"))
        self._processed_table = self._resource.Table(get_dynamodb_table_name("processed_docs"))
        self._job_runs_table = self._resource.Table(get_dynamodb_table_name("job_runs"))
        self._user_data_table = self._resource.Table(get_dynamodb_table_name("user_data"))

    # -- Analysis Results ---------------------------------------------------

    def put_analysis_result(self, result: AnalysisResult) -> None:
        """Store an analysis result in DynamoDB."""
        item = {
            "PK": f"TICKER#{result.ticker}",
            "SK": f"ANALYSIS#{result.created_at.isoformat()}#{result.source.value}",
            "result_id": result.result_id,
            "ticker": result.ticker,
            "company_name": result.company_name,
            "source": result.source.value,
            "sentiment": result.sentiment.value,
            "sentiment_confidence": result.sentiment_confidence,
            "impact_score": result.impact_score,
            "impact_direction": result.impact_direction.value,
            "summary": result.summary,
            "key_factors": result.key_factors,
            "raw_s3_path": result.raw_s3_path or "",
            "source_url": result.source_url,
            "source_title": result.source_title,
            "llm_model": result.llm_model,
            "llm_tokens_in": result.llm_tokens_in,
            "llm_tokens_out": result.llm_tokens_out,
            "created_at": result.created_at.isoformat(),
            # GSI attributes
            "GSI1PK": f"SOURCE#{result.source.value}",
            "GSI1SK": result.created_at.isoformat(),
            "GSI2PK": "IMPACT_TIER#HIGH" if result.is_high_confidence else "IMPACT_TIER#LOW",
            "GSI2SK": result.created_at.isoformat(),
        }

        item = _float_to_decimal(item)

        try:
            self._analysis_table.put_item(Item=item)
            logger.info(f"Stored analysis result: {result.result_id}")
        except ClientError as e:
            logger.error(f"Failed to store analysis result: {e}")
            raise

    def get_analyses_for_ticker(
        self,
        ticker: str,
        source: Optional[DataSource] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query analysis results for a ticker, optionally filtered by source."""
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": self._key("PK").eq(f"TICKER#{ticker}"),
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }

        if source:
            kwargs["KeyConditionExpression"] &= self._key("SK").begins_with(
                f"ANALYSIS#"
            )
            import boto3
            kwargs["FilterExpression"] = boto3.dynamodb.conditions.Attr("source").eq(source.value)

        try:
            response = self._analysis_table.query(**kwargs)
            return [_decimal_to_float(item) for item in response.get("Items", [])]
        except ClientError as e:
            logger.error(f"Failed to query analyses: {e}")
            raise

    def get_top_findings(self, limit: int = 10) -> list[dict]:
        """Get top high-confidence findings across all companies."""
        try:
            response = self._analysis_table.query(
                IndexName="GSI2",
                KeyConditionExpression=self._key("GSI2PK").eq(
                    "IMPACT_TIER#HIGH"
                ),
                ScanIndexForward=False,
                Limit=limit,
            )
            return [_decimal_to_float(item) for item in response.get("Items", [])]
        except ClientError as e:
            logger.error(f"Failed to query top findings: {e}")
            raise

    def batch_put_analysis_results(self, results: list[AnalysisResult]) -> None:
        """Batch write multiple analysis results."""
        with self._analysis_table.batch_writer() as batch:
            for result in results:
                item = {
                    "PK": f"TICKER#{result.ticker}",
                    "SK": f"ANALYSIS#{result.created_at.isoformat()}#{result.source.value}",
                    "result_id": result.result_id,
                    "ticker": result.ticker,
                    "company_name": result.company_name,
                    "source": result.source.value,
                    "sentiment": result.sentiment.value,
                    "sentiment_confidence": result.sentiment_confidence,
                    "impact_score": result.impact_score,
                    "impact_direction": result.impact_direction.value,
                    "summary": result.summary,
                    "key_factors": result.key_factors,
                    "raw_s3_path": result.raw_s3_path or "",
                    "source_url": result.source_url,
                    "source_title": result.source_title,
                    "llm_model": result.llm_model,
                    "llm_tokens_in": result.llm_tokens_in,
                    "llm_tokens_out": result.llm_tokens_out,
                    "created_at": result.created_at.isoformat(),
                    "GSI1PK": f"SOURCE#{result.source.value}",
                    "GSI1SK": result.created_at.isoformat(),
                    "GSI2PK": "IMPACT_TIER#HIGH" if result.is_high_confidence else "IMPACT_TIER#LOW",
                    "GSI2SK": result.created_at.isoformat(),
                }
                batch.put_item(Item=_float_to_decimal(item))

        logger.info(f"Batch wrote {len(results)} analysis results")

    # -- Processed Documents (Deduplication) --------------------------------

    def is_document_processed(self, source, doc_id: str) -> bool:
        """Check if a document has already been processed."""
        source_val = source.value if hasattr(source, 'value') else str(source)
        try:
            response = self._processed_table.get_item(
                Key={
                    "PK": f"SOURCE#{source_val}",
                    "SK": f"DOC#{doc_id}",
                }
            )
            return "Item" in response
        except ClientError as e:
            logger.error(f"Failed to check processed status: {e}")
            return False

    def mark_document_processed(self, source, doc_id: str, metadata: dict = None) -> None:
        """Mark a document as processed to prevent reprocessing."""
        source_val = source.value if hasattr(source, 'value') else str(source)
        item = {
            "PK": f"SOURCE#{source_val}",
            "SK": f"DOC#{doc_id}",
            "processed_at": _utcnow().isoformat(),
        }
        if metadata:
            item["metadata"] = metadata

        try:
            self._processed_table.put_item(Item=_float_to_decimal(item))
        except ClientError as e:
            logger.error(f"Failed to mark document processed: {e}")
            raise

    # -- Job Runs -----------------------------------------------------------

    def put_job_run(self, metrics: JobRunMetrics) -> None:
        """Store or update job run metrics."""
        item = {
            "PK": f"RUN#{metrics.run_id}",
            "SK": "SUMMARY",
            "run_id": metrics.run_id,
            "started_at": metrics.started_at.isoformat(),
            "completed_at": metrics.completed_at.isoformat() if metrics.completed_at else "",
            "status": metrics.status,
            "companies_processed": metrics.companies_processed,
            "documents_scraped": metrics.documents_scraped,
            "analyses_completed": metrics.analyses_completed,
            "total_tokens_in": metrics.total_tokens_in,
            "total_tokens_out": metrics.total_tokens_out,
            "total_cost_usd": metrics.total_cost_usd,
            "calls_by_provider": metrics.calls_by_provider,
            "errors": metrics.errors,
            "llm_calls": [call.model_dump() for call in metrics.llm_calls],
        }

        try:
            self._job_runs_table.put_item(Item=_float_to_decimal(item))
            logger.info(f"Stored job run metrics: {metrics.run_id}")
        except ClientError as e:
            logger.error(f"Failed to store job run: {e}")
            raise

    def get_recent_job_runs(self, limit: int = 20) -> list[dict]:
        """Get recent job runs, newest first."""
        try:
            response = self._job_runs_table.scan(Limit=limit)
            items = response.get("Items", [])
            # Sort by started_at descending
            items.sort(key=lambda x: x.get("started_at", ""), reverse=True)
            return [_decimal_to_float(item) for item in items[:limit]]
        except ClientError as e:
            logger.error(f"Failed to get job runs: {e}")
            raise

    def update_job_run(self, run_id: str, updates: dict) -> None:
        """Update fields on a job run's SUMMARY item."""
        if not updates:
            return
        expr_parts = []
        expr_values = {}
        expr_names = {}
        for i, (key, value) in enumerate(updates.items()):
            alias_name = f"#k{i}"
            alias_value = f":v{i}"
            expr_parts.append(f"{alias_name} = {alias_value}")
            expr_names[alias_name] = key
            expr_values[alias_value] = value
        try:
            self._job_runs_table.update_item(
                Key={"PK": f"RUN#{run_id}", "SK": "SUMMARY"},
                UpdateExpression="SET " + ", ".join(expr_parts),
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=_float_to_decimal(expr_values),
            )
        except ClientError as e:
            logger.error(f"Failed to update job run {run_id}: {e}")
            raise

    def put_job_logs(self, run_id: str, entries: list[dict]) -> None:
        """Store log entries for a job run as a separate item."""
        item = {
            "PK": f"RUN#{run_id}",
            "SK": "LOGS",
            "run_id": run_id,
            "entries": entries,
            "entry_count": len(entries),
            "updated_at": _utcnow().isoformat(),
        }
        try:
            self._job_runs_table.put_item(Item=_float_to_decimal(item))
            logger.info(f"Stored {len(entries)} log entries for run {run_id}")
        except ClientError as e:
            logger.error(f"Failed to store job logs: {e}")
            raise

    def get_job_logs(self, run_id: str) -> list[dict]:
        """Get log entries for a specific job run."""
        try:
            response = self._job_runs_table.get_item(
                Key={"PK": f"RUN#{run_id}", "SK": "LOGS"}
            )
            item = response.get("Item")
            if item is None:
                return []
            return _decimal_to_float(item.get("entries", []))
        except ClientError as e:
            logger.error(f"Failed to get job logs for {run_id}: {e}")
            raise

    # -- Per-user Company Lists ---------------------------------------------

    def get_user_companies(self, username: str) -> list[dict] | None:
        """Get the company list for a user from DynamoDB."""
        try:
            response = self._user_data_table.get_item(
                Key={"PK": f"USER#{username}", "SK": "COMPANIES"}
            )
            item = response.get("Item")
            if item is None:
                return None
            return _decimal_to_float(item.get("companies", []))
        except ClientError as e:
            logger.error("Failed to get user companies: %s", e)
            raise

    def put_user_companies(self, username: str, companies: list[dict]) -> None:
        """Save the full company list for a user."""
        item = {
            "PK": f"USER#{username}",
            "SK": "COMPANIES",
            "companies": companies,
            "updated_at": _utcnow().isoformat(),
        }
        try:
            self._user_data_table.put_item(Item=_float_to_decimal(item))
            logger.info("Saved %d companies for user %s", len(companies), username)
        except ClientError as e:
            logger.error("Failed to save user companies: %s", e)
            raise

    def add_user_company(self, username: str, company: dict) -> None:
        """Add a single company to a user's list. Raises ValueError on duplicate ticker."""
        companies = self.get_user_companies(username) or []
        if any(c["ticker"].upper() == company["ticker"].upper() for c in companies):
            raise ValueError(f"Company with ticker '{company['ticker']}' already exists.")
        companies.append(company)
        self.put_user_companies(username, companies)

    def remove_user_company(self, username: str, ticker: str) -> None:
        """Remove a company from a user's list by ticker. Raises ValueError if not found."""
        companies = self.get_user_companies(username) or []
        filtered = [c for c in companies if c["ticker"].upper() != ticker.upper()]
        if len(filtered) == len(companies):
            raise ValueError(f"No company found with ticker '{ticker}'.")
        self.put_user_companies(username, filtered)

    # -- User Credentials (Registration) ------------------------------------

    def get_user_credentials(self, username: str) -> dict | None:
        """Get stored credentials for a user. Returns None if user not registered."""
        try:
            response = self._user_data_table.get_item(
                Key={"PK": f"USER#{username}", "SK": "CREDENTIALS"}
            )
            item = response.get("Item")
            if item is None:
                return None
            return _decimal_to_float(item)
        except ClientError as e:
            logger.error("Failed to get user credentials: %s", e)
            raise

    def put_user_credentials(self, username: str, hashed_password: str, salt: str, email: str = "") -> None:
        """Store user credentials."""
        item = {
            "PK": f"USER#{username}",
            "SK": "CREDENTIALS",
            "hashed_password": hashed_password,
            "salt": salt,
            "email": email,
            "created_at": _utcnow().isoformat(),
        }
        try:
            self._user_data_table.put_item(Item=_float_to_decimal(item))
            logger.info("Stored credentials for user %s", username)
        except ClientError as e:
            logger.error("Failed to store user credentials: %s", e)
            raise

    def user_exists(self, username: str) -> bool:
        """Check if a user is registered."""
        return self.get_user_credentials(username) is not None

    @staticmethod
    def _key(name: str):
        """Helper to create a DynamoDB Key condition."""
        import boto3
        return boto3.dynamodb.conditions.Key(name)


# ---------------------------------------------------------------------------
# Local File-Based Storage (for development without AWS)
# ---------------------------------------------------------------------------

class LocalFileStorage:
    """
    Drop-in replacement for S3Storage that writes to local filesystem.
    Files are stored under .local_data/s3/{key}
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or os.environ.get("LOCAL_STORAGE_DIR", ".local_data/s3"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.bucket_name = "local"

    def _build_key(self, source: DataSource, ticker: str, doc_id: str) -> str:
        date_str = _utcnow().strftime("%Y-%m-%d")
        source_prefix = {
            DataSource.SEC: "sec-filings",
            DataSource.INVESTOR_PAGE: "investor-page",
            DataSource.NEWS_PAGE: "news-page",
            DataSource.REDDIT: "reddit",
            DataSource.X: "x-twitter",
        }.get(source, "other")
        return f"{source_prefix}/{ticker}/{date_str}/{doc_id}.json"

    def upload_document(self, document: ScrapedDocument) -> str:
        s3_key = self._build_key(document.source, document.ticker, document.doc_id)
        file_path = self.base_dir / s3_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = document.model_dump(mode="json")
        file_path.write_text(json.dumps(payload, default=str, indent=2))
        logger.info("Saved document locally: %s", file_path)
        return s3_key

    def download_document(self, s3_key: str) -> ScrapedDocument:
        file_path = self.base_dir / s3_key
        data = json.loads(file_path.read_text())
        return ScrapedDocument(**data)

    def list_documents(self, source: DataSource, ticker: str, date_str: Optional[str] = None) -> list[str]:
        source_prefix = {
            DataSource.SEC: "sec-filings", DataSource.INVESTOR_PAGE: "investor-page",
            DataSource.NEWS_PAGE: "news-page", DataSource.REDDIT: "reddit", DataSource.X: "x-twitter",
        }.get(source, "other")
        search_dir = self.base_dir / source_prefix / ticker
        if date_str:
            search_dir = search_dir / date_str
        if not search_dir.exists():
            return []
        return [str(p.relative_to(self.base_dir)) for p in search_dir.rglob("*.json")]


class LocalDynamoStorage:
    """
    Drop-in replacement for DynamoStorage that uses local JSON files.
    Data is stored under .local_data/dynamo/{table_name}.json
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or os.environ.get("LOCAL_STORAGE_DIR", ".local_data/dynamo"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._analysis_file = self.base_dir / "analysis_results.json"
        self._processed_file = self.base_dir / "processed_documents.json"
        self._job_runs_file = self.base_dir / "job_runs.json"
        self._user_companies_file = self.base_dir / "user_companies.json"

    def _load(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def _save(self, path: Path, data: list[dict]) -> None:
        path.write_text(json.dumps(data, default=str, indent=2))

    def put_analysis_result(self, result: AnalysisResult) -> None:
        items = self._load(self._analysis_file)
        item = {
            "PK": f"TICKER#{result.ticker}",
            "SK": f"ANALYSIS#{result.created_at.isoformat()}#{result.source.value}",
            "result_id": result.result_id, "ticker": result.ticker,
            "company_name": result.company_name, "source": result.source.value,
            "sentiment": result.sentiment.value, "sentiment_confidence": result.sentiment_confidence,
            "impact_score": result.impact_score, "impact_direction": result.impact_direction.value,
            "summary": result.summary, "key_factors": result.key_factors,
            "raw_s3_path": result.raw_s3_path or "", "source_url": result.source_url,
            "source_title": result.source_title, "llm_model": result.llm_model,
            "llm_tokens_in": result.llm_tokens_in, "llm_tokens_out": result.llm_tokens_out,
            "created_at": result.created_at.isoformat(),
            "GSI2PK": "IMPACT_TIER#HIGH" if result.is_high_confidence else "IMPACT_TIER#LOW",
        }
        # Replace existing or append
        items = [i for i in items if i.get("result_id") != result.result_id]
        items.append(item)
        self._save(self._analysis_file, items)
        logger.info("Stored analysis result locally: %s", result.result_id)

    def get_analyses_for_ticker(self, ticker: str, source: Optional[DataSource] = None, limit: int = 50) -> list[dict]:
        items = self._load(self._analysis_file)
        filtered = [i for i in items if i.get("PK") == f"TICKER#{ticker}"]
        if source:
            filtered = [i for i in filtered if i.get("source") == source.value]
        filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return filtered[:limit]

    def get_top_findings(self, limit: int = 10) -> list[dict]:
        items = self._load(self._analysis_file)
        high = [i for i in items if i.get("GSI2PK") == "IMPACT_TIER#HIGH"]
        high.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        return high[:limit]

    def batch_put_analysis_results(self, results: list[AnalysisResult]) -> None:
        for r in results:
            self.put_analysis_result(r)

    def is_document_processed(self, source, doc_id: str) -> bool:
        items = self._load(self._processed_file)
        source_val = source.value if hasattr(source, 'value') else str(source)
        pk = f"SOURCE#{source_val}"
        sk = f"DOC#{doc_id}"
        return any(i.get("PK") == pk and i.get("SK") == sk for i in items)

    def mark_document_processed(self, source, doc_id: str, metadata: dict = None) -> None:
        items = self._load(self._processed_file)
        source_val = source.value if hasattr(source, 'value') else str(source)
        item = {"PK": f"SOURCE#{source_val}", "SK": f"DOC#{doc_id}", "processed_at": _utcnow().isoformat()}
        if metadata:
            item["metadata"] = metadata
        items.append(item)
        self._save(self._processed_file, items)

    def put_job_run(self, metrics: JobRunMetrics) -> None:
        items = self._load(self._job_runs_file)
        item = {
            "PK": f"RUN#{metrics.run_id}", "SK": "SUMMARY", "run_id": metrics.run_id,
            "started_at": metrics.started_at.isoformat(),
            "completed_at": metrics.completed_at.isoformat() if metrics.completed_at else "",
            "status": metrics.status, "companies_processed": metrics.companies_processed,
            "documents_scraped": metrics.documents_scraped, "analyses_completed": metrics.analyses_completed,
            "total_tokens_in": metrics.total_tokens_in, "total_tokens_out": metrics.total_tokens_out,
            "total_cost_usd": metrics.total_cost_usd, "calls_by_provider": metrics.calls_by_provider,
            "errors": metrics.errors,
        }
        items = [i for i in items if not (i.get("run_id") == metrics.run_id and i.get("SK", "SUMMARY") == "SUMMARY")]
        items.append(item)
        self._save(self._job_runs_file, items)

    def get_recent_job_runs(self, limit: int = 20) -> list[dict]:
        items = self._load(self._job_runs_file)
        # Only return SUMMARY items, not LOGS
        items = [i for i in items if i.get("SK") == "SUMMARY" or i.get("SK") is None]
        items.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return items[:limit]

    def put_job_logs(self, run_id: str, entries: list[dict]) -> None:
        """Store log entries for a job run."""
        items = self._load(self._job_runs_file)
        # Remove existing logs for this run
        items = [i for i in items if not (i.get("PK") == f"RUN#{run_id}" and i.get("SK") == "LOGS")]
        items.append({
            "PK": f"RUN#{run_id}",
            "SK": "LOGS",
            "run_id": run_id,
            "entries": entries,
            "entry_count": len(entries),
            "updated_at": _utcnow().isoformat(),
        })
        self._save(self._job_runs_file, items)

    def get_job_logs(self, run_id: str) -> list[dict]:
        """Get log entries for a specific job run."""
        items = self._load(self._job_runs_file)
        for item in items:
            if item.get("PK") == f"RUN#{run_id}" and item.get("SK") == "LOGS":
                return item.get("entries", [])
        return []

    def update_job_run(self, run_id: str, updates: dict) -> None:
        """Update fields on a job run's SUMMARY item."""
        items = self._load(self._job_runs_file)
        for item in items:
            if item.get("PK") == f"RUN#{run_id}" and item.get("SK", "SUMMARY") == "SUMMARY":
                item.update(updates)
                break
        self._save(self._job_runs_file, items)

    # -- Per-user Company Lists ---------------------------------------------

    def get_user_companies(self, username: str) -> list[dict] | None:
        """Get the company list for a user. Returns None if user has no saved list."""
        items = self._load(self._user_companies_file)
        for item in items:
            if item.get("PK") == f"USER#{username}":
                return item.get("companies", [])
        return None

    def put_user_companies(self, username: str, companies: list[dict]) -> None:
        """Save the full company list for a user."""
        items = self._load(self._user_companies_file)
        # Remove existing entry for this user
        items = [i for i in items if i.get("PK") != f"USER#{username}"]
        items.append({
            "PK": f"USER#{username}",
            "SK": "COMPANIES",
            "companies": companies,
            "updated_at": _utcnow().isoformat(),
        })
        self._save(self._user_companies_file, items)
        logger.info("Saved %d companies for user %s", len(companies), username)

    def add_user_company(self, username: str, company: dict) -> None:
        """Add a single company to a user's list. Raises ValueError on duplicate ticker."""
        companies = self.get_user_companies(username) or []
        if any(c["ticker"].upper() == company["ticker"].upper() for c in companies):
            raise ValueError(f"Company with ticker '{company['ticker']}' already exists.")
        companies.append(company)
        self.put_user_companies(username, companies)

    def remove_user_company(self, username: str, ticker: str) -> None:
        """Remove a company from a user's list by ticker. Raises ValueError if not found."""
        companies = self.get_user_companies(username) or []
        filtered = [c for c in companies if c["ticker"].upper() != ticker.upper()]
        if len(filtered) == len(companies):
            raise ValueError(f"No company found with ticker '{ticker}'.")
        self.put_user_companies(username, filtered)

    # -- User Credentials (Registration) ------------------------------------

    def get_user_credentials(self, username: str) -> dict | None:
        items = self._load(self._user_companies_file)
        for item in items:
            if item.get("PK") == f"USER#{username}" and item.get("SK") == "CREDENTIALS":
                return item
        return None

    def put_user_credentials(self, username: str, hashed_password: str, salt: str, email: str = "") -> None:
        items = self._load(self._user_companies_file)
        # Remove existing credentials for this user
        items = [i for i in items if not (i.get("PK") == f"USER#{username}" and i.get("SK") == "CREDENTIALS")]
        items.append({
            "PK": f"USER#{username}",
            "SK": "CREDENTIALS",
            "hashed_password": hashed_password,
            "salt": salt,
            "email": email,
            "created_at": _utcnow().isoformat(),
        })
        self._save(self._user_companies_file, items)
        logger.info("Stored credentials for user %s", username)

    def user_exists(self, username: str) -> bool:
        return self.get_user_credentials(username) is not None


# ---------------------------------------------------------------------------
# Factory functions — automatically select local vs AWS storage
# ---------------------------------------------------------------------------

def create_file_storage(bucket_name: Optional[str] = None) -> S3Storage | LocalFileStorage:
    """Create the appropriate file storage backend."""
    if is_local():
        logger.info("Using LocalFileStorage (INVESTING_ASSISTANT_ENV=local)")
        return LocalFileStorage()
    return S3Storage(bucket_name)


def create_dynamo_storage() -> DynamoStorage | LocalDynamoStorage:
    """Create the appropriate DynamoDB storage backend."""
    if is_local():
        logger.info("Using LocalDynamoStorage (INVESTING_ASSISTANT_ENV=local)")
        return LocalDynamoStorage()
    return DynamoStorage()
