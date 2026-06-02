"""
Investor-page scraper for the Company Info Agent.

Fetches each company's investor relations page and extracts press releases,
filing links, and earnings announcements using a combination of common
HTML patterns (``<article>``, press-release divs, news listing sections).
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

# CSS class / id patterns commonly found on investor-relations pages.
_PRESS_RELEASE_PATTERNS: list[str] = [
    "press-release",
    "press_release",
    "pressrelease",
    "news-release",
    "news_release",
    "earnings",
    "ir-news",
    "ir_news",
    "investor-news",
]

# Date formats typically seen on investor pages.
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
    """Build a deterministic document ID for an investor-page item."""
    return f"investor_{ticker}_{_hash_url(url)}"


def _parse_date(text: str) -> Optional[str]:
    """
    Attempt to parse a date string from investor-page content.

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

    # Regex fallback — look for date-like strings in the element's text.
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
        # Relative URL → absolute.
        from urllib.parse import urljoin
        return urljoin(base_url, href)
    return base_url


def _extract_title(element: Tag) -> str:
    """Extract a title from headings or the first link inside *element*."""
    for heading_tag in ("h1", "h2", "h3", "h4"):
        heading = element.find(heading_tag)
        if heading:
            return heading.get_text(strip=True)
    # Fall back to the anchor text.
    a_tag = element.find("a")
    if a_tag:
        return a_tag.get_text(strip=True)
    # Last resort — first 120 chars of the element text.
    return element.get_text(" ", strip=True)[:120]


def _extract_summary(element: Tag) -> str:
    """Extract a summary / excerpt from *element*."""
    for tag_name in ("p", "span", "div"):
        candidates = element.find_all(tag_name, class_=re.compile(r"(desc|summary|excerpt|teaser|body|content)", re.I))
        for c in candidates:
            text = c.get_text(" ", strip=True)
            if len(text) > 30:
                return _truncate(text)
    # Fall back to the full inner text.
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
        summary = _extract_summary(article)
        content = f"{title}\n\nDate: {date_str}\n\n{summary}" if date_str else f"{title}\n\n{summary}"
        docs.append(
            ScrapedDocument(
                doc_id=_build_doc_id(ticker, link),
                source=DataSource.INVESTOR_PAGE,
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
    """Extract items matching common press-release CSS class patterns."""
    docs: list[ScrapedDocument] = []
    seen_ids: set[str] = set()

    for pattern in _PRESS_RELEASE_PATTERNS:
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
            summary = _extract_summary(element)
            content = f"{title}\n\nDate: {date_str}\n\n{summary}" if date_str else f"{title}\n\n{summary}"
            docs.append(
                ScrapedDocument(
                    doc_id=doc_id,
                    source=DataSource.INVESTOR_PAGE,
                    ticker=ticker,
                    title=title,
                    content=_truncate(content),
                    url=link,
                    metadata={"date": date_str, "extraction_strategy": f"class_pattern:{pattern}"},
                    scraped_at=datetime.utcnow(),
                )
            )
    return docs


def _extract_from_list_items(soup: BeautifulSoup, base_url: str, ticker: str) -> list[ScrapedDocument]:
    """
    Fallback extractor: look for ``<li>`` items inside sections whose
    heading mentions "press", "news", or "earnings".
    """
    docs: list[ScrapedDocument] = []
    seen_ids: set[str] = set()

    for heading in soup.find_all(re.compile(r"h[1-4]"), string=re.compile(r"(press|news|release|earnings|announcement)", re.I)):
        parent = heading.find_parent(["section", "div", "ul", "ol"])
        if not parent:
            continue
        for li in parent.find_all("li", limit=25):
            a_tag = li.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            link = _extract_link(li, base_url)
            doc_id = _build_doc_id(ticker, link)
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            date_str = _extract_date_from_element(li) or ""
            summary = li.get_text(" ", strip=True)
            content = f"{title}\n\nDate: {date_str}\n\n{summary}" if date_str else f"{title}\n\n{summary}"
            docs.append(
                ScrapedDocument(
                    doc_id=doc_id,
                    source=DataSource.INVESTOR_PAGE,
                    ticker=ticker,
                    title=title,
                    content=_truncate(content),
                    url=link,
                    metadata={"date": date_str, "extraction_strategy": "list_item"},
                    scraped_at=datetime.utcnow(),
                )
            )
    return docs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scrape_investor_page(company: Company) -> list[ScrapedDocument]:
    """
    Scrape a company's investor-relations page for press releases,
    filing links, and earnings announcements.

    Args:
        company: The :class:`Company` to scrape.  The method reads
                 ``company.investor_page_url``.

    Returns:
        A list of :class:`ScrapedDocument` objects (``DataSource.INVESTOR_PAGE``).
        Returns an empty list when the URL is ``None`` or on HTTP errors.
    """
    if not company.investor_page_url:
        logger.info("No investor page URL for %s — skipping.", company.ticker)
        return []

    url = company.investor_page_url
    logger.info("Scraping investor page for %s: %s", company.ticker, url)

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
            "HTTP %s for %s investor page (%s).",
            exc.response.status_code, company.ticker, url,
        )
        return []
    except httpx.RequestError as exc:
        logger.warning(
            "Request error scraping %s investor page: %s",
            company.ticker, exc,
        )
        return []

    soup = BeautifulSoup(response.text, "lxml")

    # Apply extraction strategies in priority order.
    documents = _extract_from_articles(soup, url, company.ticker)
    if not documents:
        documents = _extract_from_class_patterns(soup, url, company.ticker)
    if not documents:
        documents = _extract_from_list_items(soup, url, company.ticker)

    # Deduplicate by doc_id across strategies.
    seen: set[str] = set()
    unique: list[ScrapedDocument] = []
    for doc in documents:
        if doc.doc_id not in seen:
            seen.add(doc.doc_id)
            unique.append(doc)

    logger.info(
        "Extracted %d investor-page items for %s.",
        len(unique), company.ticker,
    )
    return unique
