"""
Multi-model LLM client for the InvestingAnalysisAgent.

Routes requests across three providers (Gemini, OpenAI, Anthropic)
with automatic fallback, exponential-backoff retries, and per-call
cost tracking.

Provider hierarchy
------------------
1. **Primary** — ``gemini-2.5-flash`` (cheapest, handles most documents)
2. **Fallback** — ``gpt-4o-mini`` (used when primary fails)
3. **Deep analysis** — ``claude-3-5-haiku-latest`` (complex SEC filings)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from src.shared.config import APIKeys
from src.shared.constants import LLM_PRICING
from src.shared.models import LLMCallMetrics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

_MODEL_MAP: dict[str, tuple[str, str]] = {
    # provider_key -> (provider_name, model_id)
    "gemini": ("gemini", "gemini-2.5-flash"),
    "openai": ("openai", "gpt-4o-mini"),
    "anthropic": ("anthropic", "claude-haiku-4-5-20251001"),
}

# Maximum retry attempts per provider
_MAX_RETRIES = 3

# Base delay for exponential back-off (seconds)
_BASE_DELAY_S = 1.0


class LLMClient:
    """Multi-provider LLM client with fallback and cost tracking.

    Parameters
    ----------
    primary_provider:
        Which provider to try first.  One of ``'gemini'``, ``'openai'``,
        ``'anthropic'``.  Defaults to ``'gemini'``.
    """

    def __init__(self, primary_provider: str = "gemini") -> None:
        if primary_provider not in _MODEL_MAP:
            raise ValueError(
                f"Unknown provider '{primary_provider}'. "
                f"Choose from {list(_MODEL_MAP.keys())}."
            )
        self._primary = primary_provider
        # Determine fallback order
        self._fallback_chain = self._build_fallback_chain(primary_provider)

        # Lazily-initialised SDK clients (created on first call)
        self._gemini_client: Any | None = None
        self._openai_client: Any | None = None
        self._anthropic_client: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 500,
    ) -> tuple[str, LLMCallMetrics]:
        """Send *prompt* to the LLM, returning response text and metrics.

        Tries the primary provider first.  On failure, walks through the
        fallback chain.

        Parameters
        ----------
        prompt:
            The user prompt (document content + analysis instructions).
        system_prompt:
            System-level instructions setting the analyst persona.
        max_tokens:
            Maximum tokens in the LLM response.

        Returns
        -------
        tuple[str, LLMCallMetrics]
            ``(response_text, metrics)`` where *metrics* includes
            provider, model, token counts, latency, and cost.

        Raises
        ------
        RuntimeError
            If all providers fail after exhausting retries.
        """
        last_error: Exception | None = None

        for provider_key in self._fallback_chain:
            provider_name, model_id = _MODEL_MAP[provider_key]
            try:
                text, raw_metrics = await self._call_with_retries(
                    provider_key, prompt, system_prompt, max_tokens
                )
                cost = self._calculate_cost(
                    model_id, raw_metrics["tokens_in"], raw_metrics["tokens_out"]
                )
                metrics = LLMCallMetrics(
                    provider=provider_name,
                    model=model_id,
                    tokens_in=raw_metrics["tokens_in"],
                    tokens_out=raw_metrics["tokens_out"],
                    latency_ms=raw_metrics["latency_ms"],
                    cost_usd=cost,
                )
                logger.info(
                    "LLM call succeeded",
                    extra={
                        "provider": provider_name,
                        "model": model_id,
                        "latency_ms": metrics.latency_ms,
                        "cost_usd": cost,
                    },
                )
                return text, metrics

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Provider %s failed, trying next: %s",
                    provider_key,
                    exc,
                )

        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}"
        )

    async def analyze_deep(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 500,
    ) -> tuple[str, LLMCallMetrics]:
        """Like :meth:`analyze` but forces the *anthropic* deep-analysis model.

        Use for complex SEC filings (10-K, 10-Q) that benefit from
        more capable reasoning.
        """
        provider_key = "anthropic"
        provider_name, model_id = _MODEL_MAP[provider_key]

        text, raw_metrics = await self._call_with_retries(
            provider_key, prompt, system_prompt, max_tokens
        )
        cost = self._calculate_cost(
            model_id, raw_metrics["tokens_in"], raw_metrics["tokens_out"]
        )
        metrics = LLMCallMetrics(
            provider=provider_name,
            model=model_id,
            tokens_in=raw_metrics["tokens_in"],
            tokens_out=raw_metrics["tokens_out"],
            latency_ms=raw_metrics["latency_ms"],
            cost_usd=cost,
        )
        return text, metrics

    # ------------------------------------------------------------------
    # Internal: retry wrapper
    # ------------------------------------------------------------------

    async def _call_with_retries(
        self,
        provider_key: str,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Call a single provider with exponential-backoff retries."""
        dispatch = {
            "gemini": self._call_gemini,
            "openai": self._call_openai,
            "anthropic": self._call_anthropic,
        }
        call_fn = dispatch[provider_key]

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await call_fn(prompt, system_prompt, max_tokens)
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)

                # Smart delay: if the error has a suggested retry delay, use it
                delay = _BASE_DELAY_S * (2 ** attempt)
                retry_match = re.search(r'retry\s+in\s+([\d.]+)s', exc_str, re.IGNORECASE)
                if retry_match:
                    suggested = float(retry_match.group(1))
                    delay = min(suggested + 2, 60)  # Cap at 60s, add 2s buffer

                # If it's a quota error (not rate limit), skip retries for this provider
                if 'insufficient_quota' in exc_str or 'billing' in exc_str.lower():
                    logger.warning(
                        "Provider %s has quota/billing issue, skipping retries: %s",
                        provider_key, exc_str[:200],
                    )
                    break

                logger.warning(
                    "Attempt %d/%d for %s failed (%s), retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    provider_key,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"Provider '{provider_key}' failed after {_MAX_RETRIES} attempts: "
            f"{last_exc}"
        )

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _call_gemini(
        self, prompt: str, system_prompt: str, max_tokens: int
    ) -> tuple[str, dict]:
        """Call Google Gemini (google-genai SDK).

        Uses structured JSON output via ``response_mime_type``.
        """
        if self._gemini_client is None:
            from google import genai  # type: ignore[import-untyped]

            self._gemini_client = genai.Client(
                api_key=APIKeys.gemini_api_key()
            )

        start = time.perf_counter()
        response = await asyncio.to_thread(
            self._gemini_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "system_instruction": system_prompt,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )
        latency_ms = int((time.perf_counter() - start) * 1_000)

        text = response.text or ""
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return text, {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
        }

    async def _call_openai(
        self, prompt: str, system_prompt: str, max_tokens: int
    ) -> tuple[str, dict]:
        """Call OpenAI (openai SDK).

        Requests JSON mode via ``response_format``.
        """
        if self._openai_client is None:
            from openai import OpenAI  # type: ignore[import-untyped]

            self._openai_client = OpenAI(api_key=APIKeys.openai_api_key())

        start = time.perf_counter()
        response = await asyncio.to_thread(
            self._openai_client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.perf_counter() - start) * 1_000)

        choice = response.choices[0]
        text = choice.message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0

        return text, {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
        }

    async def _call_anthropic(
        self, prompt: str, system_prompt: str, max_tokens: int
    ) -> tuple[str, dict]:
        """Call Anthropic (anthropic SDK).

        Anthropic does not have a native JSON mode, so the system
        prompt explicitly instructs the model to return valid JSON.
        """
        if self._anthropic_client is None:
            from anthropic import Anthropic  # type: ignore[import-untyped]

            self._anthropic_client = Anthropic(
                api_key=APIKeys.anthropic_api_key()
            )

        start = time.perf_counter()
        response = await asyncio.to_thread(
            self._anthropic_client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.perf_counter() - start) * 1_000)

        text = response.content[0].text if response.content else ""
        tokens_in = getattr(response.usage, "input_tokens", 0)
        tokens_out = getattr(response.usage, "output_tokens", 0)

        return text, {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fallback_chain(primary: str) -> list[str]:
        """Return an ordered list of provider keys starting with *primary*."""
        all_keys = ["gemini", "openai", "anthropic"]
        chain = [primary]
        for k in all_keys:
            if k != primary:
                chain.append(k)
        return chain

    @staticmethod
    def _calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
        """Calculate USD cost based on :data:`LLM_PRICING`."""
        pricing = LLM_PRICING.get(model)
        if not pricing:
            logger.warning("No pricing info for model '%s'; cost set to 0", model)
            return 0.0
        cost_in = (tokens_in / 1_000_000) * pricing["input"]
        cost_out = (tokens_out / 1_000_000) * pricing["output"]
        return round(cost_in + cost_out, 8)
