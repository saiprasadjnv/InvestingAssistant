"""
SEC EDGAR API client.

Provides async methods for fetching company filing metadata and
downloading filing documents from SEC EDGAR. Respects the SEC's
mandatory User-Agent header and 10-requests-per-second rate limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from src.shared.constants import (
    SEC_ARCHIVES_BASE_URL,
    SEC_FILING_TYPES_OF_INTEREST,
    SEC_MAX_REQUESTS_PER_SECOND,
    SEC_SUBMISSIONS_BASE_URL,
    SEC_USER_AGENT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limiting semaphore — limits concurrent requests to stay under
# the SEC's 10 req/s ceiling.
# ---------------------------------------------------------------------------
_request_semaphore = asyncio.Semaphore(SEC_MAX_REQUESTS_PER_SECOND)


class EDGARClient:
    """Async client for the SEC EDGAR SUBMISSIONS API.

    Usage::

        async with EDGARClient() as client:
            filings = await client.get_company_filings("320193")
    """

    def __init__(
        self,
        user_agent: str = SEC_USER_AGENT,
        timeout: float = 30.0,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    # -- Context-manager helpers -------------------------------------------

    async def __aenter__(self) -> EDGARClient:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- Internal helpers --------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        """Raise if the client has not been opened via async-with."""
        if self._client is None:
            raise RuntimeError(
                "EDGARClient must be used as an async context manager: "
                "async with EDGARClient() as client: ..."
            )
        return self._client

    @staticmethod
    def _pad_cik(cik: str) -> str:
        """Zero-pad a CIK to 10 digits as required by the EDGAR API."""
        return cik.lstrip("0").zfill(10)

    async def _rate_limited_get(self, url: str) -> httpx.Response:
        """Perform a GET request with rate-limiting.

        Acquires the semaphore and adds a 0.1 s sleep *after* the
        request so that at most 10 requests fire per second.
        """
        client = self._ensure_client()
        async with _request_semaphore:
            response = await client.get(url)
            await asyncio.sleep(1.0 / SEC_MAX_REQUESTS_PER_SECOND)  # 0.1 s
            return response

    # -- Public API --------------------------------------------------------

    async def get_company_filings(
        self,
        cik: str,
        form_types: Optional[list[str]] = None,
        max_filings: int = 50,
    ) -> list[dict]:
        """Fetch recent filings for a company from the EDGAR submissions API.

        The submissions endpoint returns filing metadata in *columnar*
        format — each field (``form``, ``filingDate``, ``accessionNumber``,
        etc.) is a parallel array.  This method zips them into a list of
        row dicts and optionally filters by form type.

        Args:
            cik: SEC Central Index Key (will be zero-padded to 10 digits).
            form_types: If provided, only return filings of these types
                        (e.g. ``["10-K", "8-K"]``).  Defaults to
                        :data:`SEC_FILING_TYPES_OF_INTEREST`.
            max_filings: Maximum number of filings to return.

        Returns:
            A list of dicts, each with keys such as ``form``,
            ``filingDate``, ``accessionNumber``, ``primaryDocument``,
            ``reportDate``, ``fileNumber``, and ``filmNumber``.
        """
        if form_types is None:
            form_types = SEC_FILING_TYPES_OF_INTEREST

        padded = self._pad_cik(cik)
        url = f"{SEC_SUBMISSIONS_BASE_URL}/CIK{padded}.json"

        logger.info("Fetching EDGAR submissions for CIK %s (%s)", cik, url)

        response = await self._rate_limited_get(url)
        response.raise_for_status()
        data = response.json()

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            logger.warning("No 'filings.recent' block in response for CIK %s", cik)
            return []

        # Columnar → row-oriented conversion.
        # All arrays in `recent` share the same length.
        column_keys = list(recent.keys())
        num_rows = len(next(iter(recent.values()), []))

        filings: list[dict] = []
        for i in range(num_rows):
            row = {key: recent[key][i] for key in column_keys}
            form = row.get("form", "")

            # Filter by form type (case-insensitive comparison).
            if form_types and form.upper() not in [ft.upper() for ft in form_types]:
                continue

            filings.append(row)
            if len(filings) >= max_filings:
                break

        logger.info(
            "Found %d filings (of %d total) for CIK %s after filtering",
            len(filings),
            num_rows,
            cik,
        )
        return filings

    def build_filing_url(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> str:
        """Build the direct URL for a filing document on SEC.gov.

        Args:
            cik: The company CIK (will be zero-padded).
            accession_number: The accession number (``0001193125-23-012345``).
            primary_document: The filename of the primary document.

        Returns:
            A fully-qualified URL to the filing document.
        """
        padded = self._pad_cik(cik)
        # Accession number in the URL path has dashes stripped.
        accession_no_dashes = accession_number.replace("-", "")
        return (
            f"{SEC_ARCHIVES_BASE_URL}/{padded}/{accession_no_dashes}/{primary_document}"
        )

    async def get_filing_document(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> str:
        """Download the HTML content of a filing document.

        Args:
            cik: The company CIK.
            accession_number: The accession number of the filing.
            primary_document: The primary document filename.

        Returns:
            The raw HTML text of the filing document.
        """
        url = self.build_filing_url(cik, accession_number, primary_document)
        logger.info("Fetching filing document: %s", url)

        response = await self._rate_limited_get(url)
        response.raise_for_status()
        return response.text
