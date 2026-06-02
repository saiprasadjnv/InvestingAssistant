"""
X/Twitter API client using Tweepy.

Authenticates with Bearer Token for v2 API access (read-only)
and searches recent tweets about tracked companies. Includes a
2-step follower filter: search by keyword, then look up each
author's follower count client-side to keep only high-influence tweets.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import tweepy

from src.shared.config import APIKeys
from src.shared.constants import X_MIN_FOLLOWERS, X_TOP_TWEETS_PER_COMPANY

logger = logging.getLogger(__name__)


class XClient:
    """Thin wrapper around the Tweepy v2 client for company tweet searches."""

    def __init__(self, bearer_token: Optional[str] = None) -> None:
        """
        Initialise the X API client.

        Args:
            bearer_token: Twitter API v2 bearer token.  Falls back to
                          ``APIKeys.x_bearer_token()`` when not supplied.
        """
        token = bearer_token or APIKeys.x_bearer_token()
        self._client = tweepy.Client(bearer_token=token, wait_on_rate_limit=True)
        # Cache: user_id -> {username, followers_count}
        self._user_cache: dict[str, dict[str, Any]] = {}
        # Counter for API read calls (for cost tracking)
        self.api_read_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_company_tweets(
        self,
        ticker: str,
        company_name: str,
        limit: int = X_TOP_TWEETS_PER_COMPANY,
    ) -> list[dict]:
        """
        Search recent tweets mentioning a company and filter by author
        follower count.

        The search covers the last 7 days (Twitter v2 ``search_recent_tweets``
        endpoint).  Retweets are excluded via the ``-is:retweet`` operator.

        Args:
            ticker:       Stock ticker symbol (e.g. ``"AAPL"``).
            company_name: Full company name used as an additional keyword.
            limit:        Maximum number of *filtered* tweets to return.

        Returns:
            A list of dicts, each containing::

                tweet_id, text, author_id, author_username,
                followers_count, created_at, retweet_count,
                like_count, reply_count
        """
        query = f"${ticker} OR {company_name} -is:retweet"
        logger.info("Searching X for query=%r  (limit=%d)", query, limit)

        # Request more than ``limit`` so we still have enough after the
        # follower filter.  The v2 search endpoint caps at 100 per request.
        max_results = min(limit * 4, 100)

        try:
            response = self._client.search_recent_tweets(
                query=query,
                max_results=max_results,
                tweet_fields=["created_at", "public_metrics", "author_id"],
            )
            self.api_read_count += 1
        except tweepy.TooManyRequests:
            logger.warning("Rate-limited while searching tweets for %s", ticker)
            return []
        except tweepy.TweepyException as exc:
            logger.error("X API error searching tweets for %s: %s", ticker, exc)
            return []

        if not response.data:
            logger.info("No tweets found for %s", ticker)
            return []

        # Step 2 – look up each author and filter by follower count
        filtered: list[dict] = []
        for tweet in response.data:
            author_id = str(tweet.author_id)
            user_info = self._get_user_info(author_id)
            if user_info is None:
                continue

            followers_count: int = user_info.get("followers_count", 0)
            if followers_count < X_MIN_FOLLOWERS:
                continue

            metrics = tweet.public_metrics or {}
            filtered.append(
                {
                    "tweet_id": str(tweet.id),
                    "text": tweet.text,
                    "author_id": author_id,
                    "author_username": user_info.get("username", ""),
                    "followers_count": followers_count,
                    "created_at": (
                        tweet.created_at.isoformat()
                        if isinstance(tweet.created_at, datetime)
                        else str(tweet.created_at)
                    ),
                    "retweet_count": metrics.get("retweet_count", 0),
                    "like_count": metrics.get("like_count", 0),
                    "reply_count": metrics.get("reply_count", 0),
                }
            )

            if len(filtered) >= limit:
                break

        logger.info(
            "Found %d tweets (of %d raw) for %s after follower filter (>=%s)",
            len(filtered),
            len(response.data),
            ticker,
            f"{X_MIN_FOLLOWERS:,}",
        )
        return filtered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_info(self, user_id: str) -> Optional[dict[str, Any]]:
        """
        Fetch user info for *user_id*, using an in-memory cache to avoid
        duplicate API calls within the same Lambda invocation.

        Args:
            user_id: Twitter numeric user ID.

        Returns:
            A dict with ``username`` and ``followers_count``, or ``None``
            on lookup failure.
        """
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        try:
            user_resp = self._client.get_user(
                id=user_id,
                user_fields=["public_metrics", "username"],
            )
            self.api_read_count += 1
        except tweepy.TooManyRequests:
            logger.warning("Rate-limited while looking up user %s", user_id)
            return None
        except tweepy.TweepyException as exc:
            logger.error("X API error looking up user %s: %s", user_id, exc)
            return None

        if not user_resp or not user_resp.data:
            logger.debug("User %s not found", user_id)
            return None

        user = user_resp.data
        public_metrics = user.public_metrics or {}
        info: dict[str, Any] = {
            "username": user.username,
            "followers_count": public_metrics.get("followers_count", 0),
        }
        self._user_cache[user_id] = info
        return info
