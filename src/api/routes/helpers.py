"""Shared helpers for API routes."""

from __future__ import annotations

import logging

from src.shared.config import load_companies
from src.shared.storage import create_dynamo_storage

logger = logging.getLogger(__name__)

_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = create_dynamo_storage()
    return _dynamo


def get_user_companies_list(username: str) -> list[dict]:
    """Get companies for a user, seeding from defaults if first time."""
    dynamo = _get_dynamo()
    companies = dynamo.get_user_companies(username)
    if companies is None:
        # First time user — seed with defaults from config
        defaults = load_companies()
        companies = [
            {
                "name": c.name,
                "ticker": c.ticker,
                "sector": getattr(c, "sector", ""),
                "cik": getattr(c, "cik", ""),
                "investor_page_url": getattr(c, "investor_page_url", ""),
                "news_page_url": getattr(c, "news_page_url", ""),
            }
            for c in defaults
        ]
        dynamo.put_user_companies(username, companies)
        logger.info("Seeded %d default companies for new user %s", len(companies), username)
    return companies
