"""
Prompt templates for LLM-based financial sentiment analysis.

Each template is a Python format-string expecting these variables:

- ``{company_name}``   — Full company name (e.g. "Apple Inc.")
- ``{ticker}``         — Stock ticker symbol (e.g. "AAPL")
- ``{content}``        — The scraped document text
- ``{source_metadata}``— Serialised JSON of source-specific metadata

Every prompt instructs the LLM to return **valid JSON** with the
following keys:

.. code-block:: json

    {{
        "sentiment": "POSITIVE | NEGATIVE | NEUTRAL",
        "sentiment_confidence": 0.0-1.0,
        "impact_direction": "UP | DOWN | NEUTRAL",
        "impact_magnitude": 0.0-1.0,
        "summary": "2-3 sentence summary",
        "key_factors": ["factor 1", "factor 2", ...]
    }}
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System prompt (shared across all source-specific prompts)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """\
You are a senior financial analyst AI specialising in equity research. \
You analyse financial documents, news articles, and social media content \
to assess their likely impact on a company's stock price.

IMPORTANT RULES:
1. Be precise, data-driven, and objective.
2. Clearly distinguish between facts, projections, and speculation.
3. Always return your analysis as a single JSON object — no markdown, no \
   extra text, no code fences.
4. If the content is ambiguous or lacks clear directional signal, set \
   sentiment to NEUTRAL and impact_magnitude close to 0.
5. Base your confidence only on the evidence provided; never hallucinate \
   facts.

OUTPUT FORMAT (return exactly this JSON structure):
{{
    "sentiment": "POSITIVE | NEGATIVE | NEUTRAL",
    "sentiment_confidence": <float 0.0-1.0>,
    "impact_direction": "UP | DOWN | NEUTRAL",
    "impact_magnitude": <float 0.0-1.0>,
    "summary": "<2-3 sentence summary of the finding>",
    "key_factors": ["<factor 1>", "<factor 2>", "..."]
}}
"""

# ---------------------------------------------------------------------------
# SEC Filing prompt
# ---------------------------------------------------------------------------

SEC_FILING_PROMPT_TEMPLATE: str = """\
Analyse the following SEC filing for **{company_name}** (ticker: {ticker}).

Focus on:
- Revenue, earnings, and margin trends vs. prior periods
- Material risk-factor changes or new disclosures
- Forward-looking guidance (revenue/EPS outlook)
- Major events: M&A, restructuring, related-party transactions
- Insider transactions or significant ownership changes
- Regulatory or litigation developments

SOURCE METADATA:
{source_metadata}

DOCUMENT CONTENT:
{content}
"""

# ---------------------------------------------------------------------------
# Company / Investor-page News prompt
# ---------------------------------------------------------------------------

COMPANY_NEWS_PROMPT_TEMPLATE: str = """\
Analyse the following news article or investor-page update about \
**{company_name}** (ticker: {ticker}).

Focus on:
- Product launches, partnerships, or strategic initiatives
- Leadership changes (CEO, CFO, board)
- Earnings surprises or pre-announcements
- Market-share shifts or competitive dynamics
- Supply-chain, pricing, or demand signals

SOURCE METADATA:
{source_metadata}

DOCUMENT CONTENT:
{content}
"""

# ---------------------------------------------------------------------------
# Reddit prompt
# ---------------------------------------------------------------------------

REDDIT_PROMPT_TEMPLATE: str = """\
Analyse the following Reddit discussion about **{company_name}** \
(ticker: {ticker}).

Focus on:
- Overall crowd sentiment (bullish, bearish, or mixed)
- Retail-investor conviction level
- Specific catalysts or price targets mentioned
- Rumour detection — flag unverified claims clearly
- Meme-stock signals (unusual hype, YOLO posts, squeeze talk)
- Comment quality and counter-arguments

SOURCE METADATA:
{source_metadata}

DOCUMENT CONTENT:
{content}
"""

# ---------------------------------------------------------------------------
# X / Twitter prompt
# ---------------------------------------------------------------------------

X_PROMPT_TEMPLATE: str = """\
Analyse the following X (Twitter) post about **{company_name}** \
(ticker: {ticker}).

Focus on:
- Author credibility (follower count, verified status)
- Breaking news vs. opinion vs. rumour
- Market-moving potential (is this new information?)
- Engagement metrics as a proxy for reach
- Alignment or contradiction with institutional consensus

SOURCE METADATA:
{source_metadata}

DOCUMENT CONTENT:
{content}
"""

# ---------------------------------------------------------------------------
# Template lookup by DataSource
# ---------------------------------------------------------------------------

from src.shared.models import DataSource  # noqa: E402

PROMPT_TEMPLATE_BY_SOURCE: dict[DataSource, str] = {
    DataSource.SEC: SEC_FILING_PROMPT_TEMPLATE,
    DataSource.INVESTOR_PAGE: COMPANY_NEWS_PROMPT_TEMPLATE,
    DataSource.NEWS_PAGE: COMPANY_NEWS_PROMPT_TEMPLATE,
    DataSource.REDDIT: REDDIT_PROMPT_TEMPLATE,
    DataSource.X: X_PROMPT_TEMPLATE,
}
