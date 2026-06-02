"""
Constants used across the InvestingAnalysisAgent.
"""

# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_XBRL_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts"
SEC_FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = "InvestingAnalysisAgent admin@investingassistant.com"
SEC_MAX_REQUESTS_PER_SECOND = 10
SEC_FILING_TYPES_OF_INTEREST = ["10-K", "10-Q", "8-K", "4", "SC 13D", "DEF 14A", "S-1"]

# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------
REDDIT_TARGET_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "StockMarket",
    "options",
    "SecurityAnalysis",
]
REDDIT_MIN_COMMENTS = 30
REDDIT_MIN_SCORE = 20
REDDIT_TOP_POSTS_PER_COMPANY = 5
REDDIT_COMMENT_MIN_SCORE = 20
REDDIT_MAX_COMMENTS_PER_POST = 10

# ---------------------------------------------------------------------------
# X / Twitter
# ---------------------------------------------------------------------------
X_MIN_FOLLOWERS = 100_000
X_TOP_TWEETS_PER_COMPANY = 5
X_USER_CACHE_TTL_HOURS = 24

# ---------------------------------------------------------------------------
# LLM Analysis
# ---------------------------------------------------------------------------
LLM_MAX_INPUT_TOKENS = 3000
LLM_MAX_OUTPUT_TOKENS = 500
IMPACT_ALERT_THRESHOLD = 0.7

# Source reliability weights for composite scoring
SOURCE_WEIGHTS = {
    "SEC": 0.9,
    "INVESTOR_PAGE": 0.8,
    "NEWS_PAGE": 0.6,
    "REDDIT": 0.4,
    "X": 0.3,
}

# LLM pricing per 1M tokens (input/output)
LLM_PRICING = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-haiku-4.5": {"input": 1.00, "output": 5.00},
}

# ---------------------------------------------------------------------------
# AWS Resource Names
# ---------------------------------------------------------------------------
S3_RAW_BUCKET_PREFIX = "investingassistant-raw"
DYNAMODB_ANALYSIS_TABLE = "InvestingAssistant-AnalysisResults"
DYNAMODB_PROCESSED_DOCS_TABLE = "InvestingAssistant-ProcessedDocuments"
DYNAMODB_JOB_RUNS_TABLE = "InvestingAssistant-JobRuns"

# S3 Key Prefixes
S3_SEC_PREFIX = "sec-filings"
S3_INVESTOR_PREFIX = "investor-page"
S3_NEWS_PREFIX = "news-page"
S3_REDDIT_PREFIX = "reddit"
S3_X_PREFIX = "x-twitter"

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
PIPELINE_SCHEDULE_HOURS = 3
PIPELINE_MAX_CONCURRENCY = 5
