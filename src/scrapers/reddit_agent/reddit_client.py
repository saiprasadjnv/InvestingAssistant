"""
Reddit API client using PRAW (Python Reddit API Wrapper).

Searches target finance subreddits for discussions about tracked
companies and returns qualifying posts with their top comments.
PRAW handles OAuth2 authentication and rate limiting (100 QPM)
automatically.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import praw
from praw.models import Submission

from src.shared.config import APIKeys
from src.shared.constants import (
    REDDIT_COMMENT_MIN_SCORE,
    REDDIT_MAX_COMMENTS_PER_POST,
    REDDIT_MIN_COMMENTS,
    REDDIT_MIN_SCORE,
    REDDIT_TARGET_SUBREDDITS,
    REDDIT_TOP_POSTS_PER_COMPANY,
)

logger = logging.getLogger(__name__)


class RedditClient:
    """
    Client that wraps PRAW to search for stock-related discussions
    across a curated list of finance-oriented subreddits.

    Attributes:
        reddit: Authenticated PRAW Reddit instance.
        subreddits: Comma-joined multireddit string used for searches.
    """

    def __init__(self) -> None:
        """
        Initialise the PRAW Reddit instance using credentials stored
        in the project's shared APIKeys configuration.
        """
        username = APIKeys.reddit_username()
        self.reddit = praw.Reddit(
            client_id=APIKeys.reddit_client_id(),
            client_secret=APIKeys.reddit_client_secret(),
            username=username,
            password=APIKeys.reddit_password(),
            user_agent=f"script:investing_assistant:v1.0 (by u/{username})",
        )
        # PRAW accepts "sub1+sub2+sub3" as a multi-subreddit
        self.subreddits = "+".join(REDDIT_TARGET_SUBREDDITS)
        logger.info(
            "RedditClient initialised — targeting subreddits: %s",
            self.subreddits,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_company_discussions(
        self,
        ticker: str,
        company_name: str,
        limit: int = REDDIT_TOP_POSTS_PER_COMPANY,
    ) -> list[dict[str, Any]]:
        """
        Search Reddit for discussions mentioning a company.

        The query uses the stock ticker symbol OR the company name so
        we capture both "$AAPL" posts and "Apple earnings" posts.
        Results are sorted by *top* within the last day, then
        filtered client-side for minimum engagement thresholds.

        Args:
            ticker: Stock ticker symbol (e.g. ``"AAPL"``).
            company_name: Full company name (e.g. ``"Apple Inc."``).
            limit: Maximum number of qualifying posts to return.

        Returns:
            A list of dicts, each representing a qualifying post
            with its top comments attached.
        """
        query = f'"{ticker}" OR "{company_name}"'
        logger.info(
            "Searching r/%s for query=%r  (limit=%d)",
            self.subreddits,
            query,
            limit,
        )

        qualifying_posts: list[dict[str, Any]] = []

        try:
            subreddit = self.reddit.subreddit(self.subreddits)
            # Fetch more results than needed so we can filter down
            search_results = subreddit.search(
                query,
                sort="top",
                time_filter="day",
                limit=limit * 5,
            )

            for post in search_results:
                if len(qualifying_posts) >= limit:
                    break

                # Client-side engagement filters
                if post.num_comments < REDDIT_MIN_COMMENTS:
                    continue
                if post.score < REDDIT_MIN_SCORE:
                    continue

                top_comments = self._get_top_comments(
                    post,
                    min_score=REDDIT_COMMENT_MIN_SCORE,
                    limit=REDDIT_MAX_COMMENTS_PER_POST,
                )

                qualifying_posts.append(
                    {
                        "title": post.title,
                        "selftext": post.selftext or "",
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "author": str(post.author) if post.author else "[deleted]",
                        "permalink": post.permalink,
                        "created_utc": post.created_utc,
                        "subreddit": str(post.subreddit),
                        "post_id": post.id,
                        "top_comments": top_comments,
                    }
                )

            logger.info(
                "Found %d qualifying posts for %s (%s)",
                len(qualifying_posts),
                ticker,
                company_name,
            )

        except Exception:
            logger.exception(
                "Error searching Reddit for %s (%s)", ticker, company_name
            )

        return qualifying_posts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_top_comments(
        self,
        post: Submission,
        min_score: int = REDDIT_COMMENT_MIN_SCORE,
        limit: int = REDDIT_MAX_COMMENTS_PER_POST,
    ) -> list[dict[str, Any]]:
        """
        Fetch top-level comments from a post, sorted by score.

        Only comments that meet the ``min_score`` threshold are
        returned, up to ``limit`` results.

        Args:
            post: A PRAW ``Submission`` instance.
            min_score: Minimum comment score to include.
            limit: Maximum number of comments to return.

        Returns:
            A list of comment dicts with body, score, author,
            and created_utc.
        """
        try:
            # Replace "MoreComments" objects so we get a flat list
            post.comments.replace_more(limit=0)
            all_comments = post.comments.list()

            # Sort descending by score, filter by threshold
            sorted_comments = sorted(
                all_comments,
                key=lambda c: c.score,
                reverse=True,
            )

            result: list[dict[str, Any]] = []
            for comment in sorted_comments:
                if len(result) >= limit:
                    break
                if comment.score < min_score:
                    continue

                result.append(
                    {
                        "body": comment.body,
                        "score": comment.score,
                        "author": str(comment.author) if comment.author else "[deleted]",
                        "created_utc": comment.created_utc,
                    }
                )

            return result

        except Exception:
            logger.exception(
                "Error fetching comments for post %s", post.id
            )
            return []
