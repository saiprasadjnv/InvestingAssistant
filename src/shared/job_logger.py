"""
Job Logger — Structured logging for pipeline runs with incremental streaming.

Logs are collected in memory and flushed incrementally to DynamoDB
(PK=RUN#{run_id}, SK=LOGS) after each meaningful event. The frontend
polls every 2 seconds to display streaming logs.

Cost per run (~60s, 11 companies):
  - Writes: ~20 put_item × 40KB = $0.0000025
  - Reads:  ~30 get_item × 40KB = $0.0000008
  - Total:  < $0.000004 ≈ FREE
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class Stage(str, Enum):
    INIT = "INIT"
    SEC_SCRAPER = "SEC_SCRAPER"
    COMPANY_INFO = "COMPANY_INFO"
    REDDIT_SCRAPER = "REDDIT_SCRAPER"
    X_SCRAPER = "X_SCRAPER"
    SENTIMENT = "SENTIMENT"
    IMPACT_SCORER = "IMPACT_SCORER"
    COMPLETE = "COMPLETE"


class JobLogger:
    """Structured logger for pipeline job runs with incremental DynamoDB flushing."""

    def __init__(self, run_id: str, storage=None):
        self.run_id = run_id
        self.entries: list[dict[str, Any]] = []
        self._start_time = datetime.now(timezone.utc)
        self._storage = storage
        self._last_flushed_count = 0  # Track what we've already flushed

    def set_storage(self, storage):
        """Set or update the storage backend for incremental flushing."""
        self._storage = storage

    def info(self, stage: Stage, message: str, **details):
        self._add(LogLevel.INFO, stage, message, details)

    def warn(self, stage: Stage, message: str, **details):
        self._add(LogLevel.WARN, stage, message, details)

    def error(self, stage: Stage, message: str, exc: Exception = None, **details):
        if exc:
            details["exception"] = f"{type(exc).__name__}: {str(exc)}"
            details["traceback"] = traceback.format_exc(limit=5)
        self._add(LogLevel.ERROR, stage, message, details)

    def debug(self, stage: Stage, message: str, **details):
        self._add(LogLevel.DEBUG, stage, message, details)

    def company_start(self, stage: Stage, ticker: str):
        self.info(stage, f"Processing {ticker}", ticker=ticker)

    def company_done(self, stage: Stage, ticker: str, docs_found: int = 0, new_docs: int = 0):
        self.info(
            stage,
            f"{ticker}: found {docs_found} docs, {new_docs} new",
            ticker=ticker, docs_found=docs_found, new_docs=new_docs,
        )
        self._auto_flush()  # Stream after each company

    def company_error(self, stage: Stage, ticker: str, exc: Exception):
        self.error(stage, f"{ticker}: failed", exc=exc, ticker=ticker)
        self._auto_flush()  # Stream errors immediately

    def stage_start(self, stage: Stage, company_count: int = 0):
        self.info(stage, f"Stage started ({company_count} companies)", company_count=company_count)
        self._auto_flush()  # Stream stage transitions

    def stage_done(self, stage: Stage, total_docs: int = 0, duration_ms: int = 0):
        self.info(stage, f"Stage complete: {total_docs} docs in {duration_ms}ms", total_docs=total_docs, duration_ms=duration_ms)
        self._auto_flush()  # Stream stage completions

    def _add(self, level: LogLevel, stage: Stage, message: str, details: dict):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level.value,
            "stage": stage.value,
            "msg": message,
        }
        # Only include non-empty details
        clean_details = {k: v for k, v in details.items() if v is not None and v != ""}
        if clean_details:
            entry["details"] = clean_details
        self.entries.append(entry)

    def _auto_flush(self):
        """Incrementally flush new entries to DynamoDB (if storage is set)."""
        if not self._storage:
            return
        if len(self.entries) == self._last_flushed_count:
            return  # Nothing new to flush
        try:
            self._storage.put_job_logs(self.run_id, self.entries)
            self._last_flushed_count = len(self.entries)
        except Exception as exc:
            _logger.error("Auto-flush failed for %s: %s", self.run_id, exc)

    def flush(self, storage=None) -> None:
        """Final flush — persist all log entries to DynamoDB."""
        if storage:
            self._storage = storage
        elapsed_ms = int((datetime.now(timezone.utc) - self._start_time).total_seconds() * 1000)
        self.info(Stage.COMPLETE, f"Run finished in {elapsed_ms}ms", total_entries=len(self.entries), elapsed_ms=elapsed_ms)
        if self._storage:
            try:
                self._storage.put_job_logs(self.run_id, self.entries)
                self._last_flushed_count = len(self.entries)
            except Exception as exc:
                _logger.error("Failed to flush job logs for %s: %s", self.run_id, exc)

    def get_entries(self) -> list[dict]:
        return list(self.entries)
