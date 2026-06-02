"""
SEC filing document parser.

Extracts structured text content from raw HTML filings retrieved from
SEC EDGAR.  Uses BeautifulSoup to strip HTML, then locates key sections
(Risk Factors, MD&A, 8-K event descriptions) and truncates the output
to approximately 3 000 LLM tokens (~12 000 characters).
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

from src.shared.constants import LLM_MAX_INPUT_TOKENS
from src.shared.models import DataSource, ScrapedDocument, SECFilingMetadata

logger = logging.getLogger(__name__)

# Approximate character-per-token ratio (conservative for English text).
_CHARS_PER_TOKEN = 4
_MAX_CONTENT_CHARS = LLM_MAX_INPUT_TOKENS * _CHARS_PER_TOKEN  # ~12 000


# ---------------------------------------------------------------------------
# Section heading patterns
# ---------------------------------------------------------------------------

# 10-K / 10-Q section headings we want to capture.
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Risk Factors",
        re.compile(
            r"(?:item\s*1a[\.\s:\-]*)?risk\s+factors",
            re.IGNORECASE,
        ),
    ),
    (
        "MD&A",
        re.compile(
            r"(?:item\s*7[\.\s:\-]*)?"
            r"management['']?s?\s+discussion\s+and\s+analysis",
            re.IGNORECASE,
        ),
    ),
    (
        "Business Overview",
        re.compile(
            r"(?:item\s*1[\.\s:\-]*)?business",
            re.IGNORECASE,
        ),
    ),
    (
        "Financial Statements",
        re.compile(
            r"(?:item\s*8[\.\s:\-]*)?financial\s+statements",
            re.IGNORECASE,
        ),
    ),
]

# 8-K item/event patterns.
_8K_ITEM_PATTERN = re.compile(
    r"item\s+(\d+\.\d+)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_filing(
    html_content: str,
    ticker: str,
    filing_metadata: dict,
    filing_url: str,
) -> ScrapedDocument:
    """Parse an SEC filing HTML document into a :class:`ScrapedDocument`.

    Args:
        html_content: Raw HTML of the filing.
        ticker: Company ticker symbol.
        filing_metadata: Row dict from :meth:`EDGARClient.get_company_filings`.
            Expected keys: ``form``, ``filingDate``, ``accessionNumber``,
            ``primaryDocument``, ``reportDate``.
        filing_url: Direct URL to the filing on SEC.gov.

    Returns:
        A :class:`ScrapedDocument` with truncated content suitable for
        LLM consumption and :class:`SECFilingMetadata` in the metadata field.
    """
    form_type: str = filing_metadata.get("form", "UNKNOWN")
    filing_date: str = filing_metadata.get("filingDate", "")
    accession_number: str = filing_metadata.get("accessionNumber", "")
    primary_document: str = filing_metadata.get("primaryDocument", "")
    report_date: str = filing_metadata.get("reportDate", "")

    # ---- Extract plain text from HTML ------------------------------------
    try:
        soup = BeautifulSoup(html_content, "lxml")
    except Exception:
        soup = BeautifulSoup(html_content, "html.parser")

    # Remove script / style noise.
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()

    full_text = soup.get_text(separator="\n", strip=True)

    # ---- Extract relevant sections based on form type --------------------
    if form_type.upper() in ("10-K", "10-Q"):
        content = _extract_annual_quarterly_sections(full_text)
    elif form_type.upper() == "8-K":
        content = _extract_8k_content(full_text)
    else:
        # For 4, SC 13D, DEF 14A, S-1, etc. — grab the first chunk.
        content = _truncate(full_text)

    title = _build_title(form_type, ticker, filing_date)

    # ---- Build unique document ID ----------------------------------------
    doc_hash = hashlib.sha256(
        f"{accession_number}:{primary_document}".encode()
    ).hexdigest()[:12]
    doc_id = f"SEC_{ticker}_{doc_hash}"

    # ---- Metadata --------------------------------------------------------
    sec_meta = SECFilingMetadata(
        accession_number=accession_number,
        filing_date=filing_date,
        form_type=form_type,
        report_date=report_date or None,
        primary_document=primary_document,
        filing_url=filing_url,
    )

    return ScrapedDocument(
        doc_id=doc_id,
        source=DataSource.SEC,
        ticker=ticker,
        title=title,
        content=content,
        url=filing_url,
        metadata=sec_meta.model_dump(),
        scraped_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

def _extract_annual_quarterly_sections(full_text: str) -> str:
    """Extract Risk Factors and MD&A sections from 10-K / 10-Q text.

    Falls back to the first ``_MAX_CONTENT_CHARS`` characters of the
    full text if no recognisable section headings are found.
    """
    sections: list[str] = []

    for section_name, pattern in _SECTION_PATTERNS[:2]:  # Risk Factors & MD&A
        extracted = _extract_section(full_text, pattern)
        if extracted:
            header = f"=== {section_name} ===\n"
            sections.append(header + extracted)

    if sections:
        combined = "\n\n".join(sections)
        return _truncate(combined)

    # Fallback: no sections found — return head of the document.
    logger.debug("No named sections found; falling back to head-of-document.")
    return _truncate(full_text)


def _extract_8k_content(full_text: str) -> str:
    """Extract event description from an 8-K filing.

    Captures all text under ``Item X.XX`` headings.
    """
    items: list[str] = []
    matches = list(_8K_ITEM_PATTERN.finditer(full_text))

    if not matches:
        return _truncate(full_text)

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        chunk = full_text[start:end].strip()
        items.append(chunk)

    combined = "\n\n".join(items)
    return _truncate(combined)


def _extract_section(
    text: str,
    heading_pattern: re.Pattern[str],
) -> Optional[str]:
    """Extract text starting at *heading_pattern* until the next major heading.

    Returns ``None`` if the heading is not found.
    """
    match = heading_pattern.search(text)
    if not match:
        return None

    start = match.start()
    # Look for the *next* section heading (``Item ...``) or end.
    next_heading = re.search(
        r"\n\s*item\s+\d+[a-z]?[\.\s:\-]",
        text[match.end():],
        re.IGNORECASE,
    )
    end = match.end() + next_heading.start() if next_heading else start + _MAX_CONTENT_CHARS
    return text[start:end].strip()


def _build_title(form_type: str, ticker: str, filing_date: str) -> str:
    """Build a human-readable title for the filing."""
    date_str = filing_date if filing_date else "unknown date"
    return f"SEC {form_type} Filing — {ticker} ({date_str})"


def _truncate(text: str) -> str:
    """Truncate *text* to ``_MAX_CONTENT_CHARS`` on a word boundary."""
    if len(text) <= _MAX_CONTENT_CHARS:
        return text
    # Find the last space before the limit so we don't cut mid-word.
    cut = text.rfind(" ", 0, _MAX_CONTENT_CHARS)
    if cut == -1:
        cut = _MAX_CONTENT_CHARS
    return text[:cut] + "\n\n[... content truncated for LLM consumption ...]"
