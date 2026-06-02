"""
Data models for the InvestingAnalysisAgent.

Defines all shared Pydantic models, enums, and type definitions
used across scrapers, analyzers, API, and storage layers.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DataSource(str, Enum):
    """Origin of a scraped document."""
    SEC = "SEC"
    INVESTOR_PAGE = "INVESTOR_PAGE"
    NEWS_PAGE = "NEWS_PAGE"
    REDDIT = "REDDIT"
    X = "X"


class Sentiment(str, Enum):
    """Sentiment classification."""
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class ImpactDirection(str, Enum):
    """Expected direction of stock price impact."""
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class FilingType(str, Enum):
    """SEC filing types of interest."""
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"
    FORM_4 = "4"
    FORM_SC13D = "SC 13D"
    FORM_DEF14A = "DEF 14A"
    FORM_S1 = "S-1"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

class Company(BaseModel):
    """A company being tracked by the agent."""
    name: str
    ticker: str
    sector: str
    cik: str = Field(description="SEC Central Index Key, zero-padded to 10 digits for API calls")
    investor_page_url: Optional[str] = None
    news_page_url: Optional[str] = None

    @property
    def cik_padded(self) -> str:
        """Return CIK zero-padded to 10 digits for SEC API calls."""
        return self.cik.lstrip("0").zfill(10)


# ---------------------------------------------------------------------------
# Scraped Data
# ---------------------------------------------------------------------------

class ScrapedDocument(BaseModel):
    """A raw document fetched by a scraper agent."""
    doc_id: str = Field(description="Unique identifier: {source}_{ticker}_{hash}")
    source: DataSource
    ticker: str
    title: str
    content: str = Field(description="Main text content, truncated to ~3000 tokens for LLM")
    url: str = Field(description="Original source URL")
    s3_key: Optional[str] = Field(default=None, description="S3 key where raw content is stored")
    metadata: dict = Field(default_factory=dict, description="Source-specific metadata")
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class SECFilingMetadata(BaseModel):
    """Metadata specific to SEC filings."""
    accession_number: str
    filing_date: str
    form_type: str
    report_date: Optional[str] = None
    primary_document: str
    filing_url: str
    entities: list[str] = Field(default_factory=list)


class RedditPostMetadata(BaseModel):
    """Metadata specific to Reddit posts."""
    post_id: str
    subreddit: str
    score: int
    num_comments: int
    author: str
    permalink: str
    top_comments: list[dict] = Field(default_factory=list)


class TweetMetadata(BaseModel):
    """Metadata specific to X/Twitter posts."""
    tweet_id: str
    author_id: str
    author_username: str
    author_followers: int
    retweet_count: int
    like_count: int
    reply_count: int


# ---------------------------------------------------------------------------
# Analysis Results
# ---------------------------------------------------------------------------

class AnalysisResult(BaseModel):
    """Result of LLM-based analysis on a scraped document."""
    result_id: str = Field(description="Unique ID: {ticker}_{source}_{timestamp}")
    ticker: str
    company_name: str
    source: DataSource
    sentiment: Sentiment
    sentiment_confidence: float = Field(ge=0.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0, description="Composite stock impact confidence")
    impact_direction: ImpactDirection
    summary: str = Field(description="LLM-generated summary of the finding")
    key_factors: list[str] = Field(default_factory=list, description="Key factors driving the analysis")
    raw_s3_path: Optional[str] = None
    source_url: str = ""
    source_title: str = ""
    llm_model: str = ""
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_high_confidence(self) -> bool:
        """Check if this finding crosses the alert threshold."""
        return self.impact_score >= 0.7


# ---------------------------------------------------------------------------
# Job Run Tracking
# ---------------------------------------------------------------------------

class LLMCallMetrics(BaseModel):
    """Metrics for a single LLM API call."""
    provider: str  # "gemini", "openai", "anthropic"
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float = 0.0


class JobRunMetrics(BaseModel):
    """Aggregate metrics for a single pipeline run."""
    run_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"  # RUNNING, COMPLETED, FAILED
    companies_processed: int = 0
    documents_scraped: int = 0
    analyses_completed: int = 0
    llm_calls: list[LLMCallMetrics] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def total_tokens_in(self) -> int:
        return sum(c.tokens_in for c in self.llm_calls)

    @property
    def total_tokens_out(self) -> int:
        return sum(c.tokens_out for c in self.llm_calls)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.llm_calls)

    @property
    def calls_by_provider(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.llm_calls:
            counts[c.provider] = counts.get(c.provider, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Pipeline Event (passed between Step Functions states)
# ---------------------------------------------------------------------------

class PipelineEvent(BaseModel):
    """Event payload passed through the Step Functions pipeline."""
    run_id: str
    companies: list[Company]
    scraped_documents: list[ScrapedDocument] = Field(default_factory=list)
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    job_metrics: Optional[JobRunMetrics] = None
