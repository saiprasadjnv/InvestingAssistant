"""
News-page scraper for the Company Info Agent.

Fetches each company's news / blog page and extracts article summaries,
titles, and publication dates.  Content is truncated to ~3 000 tokens
before being stored as :class:`ScrapedDocument` items.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from src.shared.models import Company, DataSource, ScrapedDocument
from src.shared.constants import LLM_MAX_INPUT_TOKENS

logger = logging.getLogger(__name__)

# Rough chars-per-token multiplier (conservative).
_CHARS_PER_TOKEN = 4
_MAX_CONTENT_CHARS = LLM_MAX_INPUT_TOKENS * _CHARS_PER_TOKEN  # ~12 000 chars

_REQUEST_TIMEOUT = 30.0  # seconds

_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestingAnalysisAgent/1.0; "
    "+https://github.com/investingassistant)"
)

# CSS class / id patterns commonly found on corporate news / blog pages.
_NEWS_PATTERNS: list[str] = [
    "news-item",
    "news_item",
    "newsitem",
    "news-card",
    "news_card",
    "blog-post",
    "blog_post",
    "blogpost",
    "post-card",
    "post_card",
    "story-card",
    "story_card",
    "news-article",
    "news_article",
    "media-item",
    "media_item",
]

# Date formats typically seen on news pages.
_DATE_FORMATS: list[str] = [
    "%B %d, %Y",      # January 15, 2025
    "%b %d, %Y",      # Jan 15, 2025
    "%Y-%m-%d",        # 2025-01-15
    "%m/%d/%Y",        # 01/15/2025
    "%d %B %Y",        # 15 January 2025
    "%d %b %Y",        # 15 Jan 2025
    "%B %d %Y",        # January 15 2025
    "%m-%d-%Y",        # 01-15-2025
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_url(url: str) -> str:
    """Return an 8-char hex digest uniquely identifying a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def _build_doc_id(ticker: str, url: str) -> str:
    """Build a deterministic document ID for a news-page item."""
    return f"news_{ticker}_{_hash_url(url)}"


def _parse_date(text: str) -> Optional[str]:
    """
    Attempt to parse a date string.

    Returns:
        ISO-format date string on success, ``None`` otherwise.
    """
    cleaned = text.strip().rstrip(".")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _extract_date_from_element(element: Tag) -> Optional[str]:
    """
    Try to find a date within *element* or its immediate descendants.

    Looks at ``<time>``, ``datetime`` attributes, and common class names
    before falling back to regex extraction from text.
    """
    # <time datetime="…">
    time_tag = element.find("time")
    if time_tag:
        dt_attr = time_tag.get("datetime", "")
        if dt_attr:
            return _parse_date(dt_attr) or dt_attr[:10]
        return _parse_date(time_tag.get_text(strip=True))

    # Elements with class containing "date"
    date_el = element.find(class_=re.compile(r"date", re.I))
    if date_el:
        parsed = _parse_date(date_el.get_text(strip=True))
        if parsed:
            return parsed

    # Regex fallback.
    text = element.get_text(" ", strip=True)
    date_match = re.search(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"\w+ \d{1,2},? \d{4}|"
        r"\d{4}-\d{2}-\d{2})\b",
        text,
    )
    if date_match:
        return _parse_date(date_match.group(0))

    return None


def _truncate(text: str, max_chars: int = _MAX_CONTENT_CHARS) -> str:
    """Truncate *text* to approximately *max_chars* characters."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def _extract_link(element: Tag, base_url: str) -> str:
    """Return the first ``href`` found in *element*, resolved against *base_url*."""
    a_tag = element.find("a", href=True)
    if a_tag:
        href = a_tag["href"]
        if href.startswith("http"):
            return href
        from urllib.parse import urljoin
        return urljoin(base_url, href)
    return base_url


def _extract_title(element: Tag) -> str:
    """Extract a title from headings or the first link inside *element*."""
    for heading_tag in ("h1", "h2", "h3", "h4"):
        heading = element.find(heading_tag)
        if heading:
            return heading.get_text(strip=True)
    a_tag = element.find("a")
    if a_tag:
        return a_tag.get_text(strip=True)
    return element.get_text(" ", strip=True)[:120]


def _extract_content(element: Tag) -> str:
    """
    Extract article body / summary content from *element*.

    Tries to locate paragraph or content-like children first; falls back
    to the full inner text.
    """
    # Look for explicit summary / excerpt containers.
    for tag_name in ("p", "span", "div"):
        candidates = element.find_all(
            tag_name,
            class_=re.compile(r"(desc|summary|excerpt|teaser|body|content|text)", re.I),
        )
        for c in candidates:
            text = c.get_text(" ", strip=True)
            if len(text) > 30:
                return _truncate(text)

    # Collect all <p> text.
    paragraphs = element.find_all("p")
    if paragraphs:
        combined = "\n\n".join(p.get_text(" ", strip=True) for p in paragraphs if p.get_text(strip=True))
        if len(combined) > 30:
            return _truncate(combined)

    # Fallback.
    return _truncate(element.get_text(" ", strip=True))


# ---------------------------------------------------------------------------
# Extraction strategies
# ---------------------------------------------------------------------------

def _extract_from_articles(soup: BeautifulSoup, base_url: str, ticker: str) -> list[ScrapedDocument]:
    """Extract items from ``<article>`` elements."""
    docs: list[ScrapedDocument] = []
    for article in soup.find_all("article", limit=25):
        title = _extract_title(article)
        if not title:
            continue
        link = _extract_link(article, base_url)
        date_str = _extract_date_from_element(article) or ""
        body = _extract_content(article)
        content = f"{title}\n\nDate: {date_str}\n\n{body}" if date_str else f"{title}\n\n{body}"
        docs.append(
            ScrapedDocument(
                doc_id=_build_doc_id(ticker, link),
                source=DataSource.NEWS_PAGE,
                ticker=ticker,
                title=title,
                content=_truncate(content),
                url=link,
                metadata={"date": date_str, "extraction_strategy": "article_tag"},
                scraped_at=datetime.utcnow(),
            )
        )
    return docs


def _extract_from_class_patterns(soup: BeautifulSoup, base_url: str, ticker: str) -> list[ScrapedDocument]:
    """Extract items matching common news CSS class patterns."""
    docs: list[ScrapedDocument] = []
    seen_ids: set[str] = set()

    for pattern in _NEWS_PATTERNS:
        matches = soup.find_all(class_=re.compile(pattern, re.I), limit=25)
        for element in matches:
            title = _extract_title(element)
            if not title or len(title) < 5:
                continue
            link = _extract_link(element, base_url)
            doc_id = _build_doc_id(ticker, link)
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            date_str = _extract_date_from_element(element) or ""
            body = _extract_content(element)
            content = f"{title}\n\nDate: {date_str}\n\n{body}" if date_str else f"{title}\n\n{body}"
            docs.append(
                ScrapedDocument(
                    doc_id=doc_id,
                    source=DataSource.NEWS_PAGE,
                    ticker=ticker,
                    title=title,
                    content=_truncate(content),
                    url=link,
                    metadata={"date": date_str, "extraction_strategy": f"class_pattern:{pattern}"},
                    scraped_at=datetime.utcnow(),
                )
            )
    return docs


def _extract_from_sections(soup: BeautifulSoup, base_url: str, ticker: str) -> list[ScrapedDocument]:
    """
    Fallback extractor: find headings that mention "news", "blog", or
    "stories" and extract children of their parent section.
    """
    docs: list[ScrapedDocument] = []
    seen_ids: set[str] = set()

    for heading in soup.find_all(
        re.compile(r"h[1-4]"),
        string=re.compile(r"(news|blog|stories|articles|latest|updates|media)", re.I),
    ):
        parent = heading.find_parent(["section", "div", "ul", "ol"])
        if not parent:
            continue
        # Try <li> items first, then direct child divs.
        items = parent.find_all("li", limit=25) or parent.find_all("div", recursive=False, limit=25)
        for item in items:
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            link = _extract_link(item, base_url)
            doc_id = _build_doc_id(ticker, link)
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            date_str = _extract_date_from_element(item) or ""
            body = item.get_text(" ", strip=True)
            content = f"{title}\n\nDate: {date_str}\n\n{body}" if date_str else f"{title}\n\n{body}"
            docs.append(
                ScrapedDocument(
                    doc_id=doc_id,
                    source=DataSource.NEWS_PAGE,
                    ticker=ticker,
                    title=title,
                    content=_truncate(content),
                    url=link,
                    metadata={"date": date_str, "extraction_strategy": "section_heading"},
                    scraped_at=datetime.utcnow(),
                )
            )
    return docs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scrape_news_page(company: Company) -> list[ScrapedDocument]:
    """
    Scrape a company's news / blog page for articles.

    Args:
        company: The :class:`Company` to scrape.  The method reads
                 ``company.news_page_url``.

    Returns:
        A list of :class:`ScrapedDocument` objects (``DataSource.NEWS_PAGE``).
        Returns an empty list when the URL is ``None`` or on HTTP errors.
    """
    if not company.news_page_url:
        logger.info("No news page URL for %s — skipping.", company.ticker)
        return []

    url = company.news_page_url
    logger.info("Scraping news page for %s: %s", company.ticker, url)

    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s for %s news page (%s).",
            exc.response.status_code, company.ticker, url,
        )
        return []
    except httpx.RequestError as exc:
        logger.warning(
            "Request error scraping %s news page: %s",
            company.ticker, exc,
        )
        return []

    soup = BeautifulSoup(response.text, "lxml")

    # Apply extraction strategies in priority order.
    documents = _extract_from_articles(soup, url, company.ticker)
    if not documents:
        documents = _extract_from_class_patterns(soup, url, company.ticker)
    if not documents:
        documents = _extract_from_sections(soup, url, company.ticker)

    # Deduplicate by doc_id.
    seen: set[str] = set()
    unique: list[ScrapedDocument] = []
    for doc in documents:
        if doc.doc_id not in seen:
            seen.add(doc.doc_id)
            unique.append(doc)

    logger.info(
        "Extracted %d news-page items for %s.",
        len(unique), company.ticker,
    )
    return unique
