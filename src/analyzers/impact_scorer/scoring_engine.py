"""
Stock Impact Scoring Engine.

Computes a composite impact score for each :class:`AnalysisResult`
by combining:

- **LLM confidence** — the model's own ``impact_magnitude`` output
- **Source reliability weight** — SEC filings carry more weight than
  tweets
- **Recency factor** — exponential decay so older signals fade
- **Corroboration bonus** — small boost when multiple independent
  sources agree on direction

The composite score lives on [0.0, 1.0] and drives alert generation.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from src.shared.constants import IMPACT_ALERT_THRESHOLD, SOURCE_WEIGHTS
from src.shared.models import AnalysisResult, DataSource, ImpactDirection
from src.shared.storage import DynamoStorage

logger = logging.getLogger(__name__)

# Half-life for recency decay (days). At 7 days, weight ≈ 0.5.
_RECENCY_HALF_LIFE_DAYS: float = 7.0

# Maximum corroboration bonus added to the composite score.
_MAX_CORROBORATION_BONUS: float = 0.2

# Minimum number of corroborating sources to earn a bonus.
_MIN_CORROBORATING_SOURCES: int = 2


class ImpactScorer:
    """Computes and evaluates composite stock-impact scores."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_composite_score(self, result: AnalysisResult) -> float:
        """Compute a composite impact score in ``[0.0, 1.0]``.

        Formula::

            score = impact_magnitude × source_weight × recency_factor

        where each factor is clamped to [0.0, 1.0].

        Parameters
        ----------
        result:
            An :class:`AnalysisResult` produced by the sentiment analyser.

        Returns
        -------
        float
            Composite score between 0.0 and 1.0.
        """
        llm_magnitude = max(0.0, min(1.0, result.impact_score))
        source_weight = self._get_source_weight(result.source)
        recency = self._recency_factor(result.created_at)

        raw_score = llm_magnitude * source_weight * recency
        return round(max(0.0, min(1.0, raw_score)), 4)

    def check_corroboration(
        self,
        ticker: str,
        direction: ImpactDirection,
        storage: DynamoStorage,
        *,
        lookback_limit: int = 20,
    ) -> float:
        """Check if other recent sources agree on the direction.

        Queries the latest ``lookback_limit`` analyses for *ticker* and
        counts how many share the same ``impact_direction``.  A bonus
        in ``[0.0, 0.2]`` is returned proportionally.

        Parameters
        ----------
        ticker:
            Stock ticker to look up.
        direction:
            The direction to corroborate.
        storage:
            :class:`DynamoStorage` instance for querying.
        lookback_limit:
            Maximum number of recent analyses to examine.

        Returns
        -------
        float
            Bonus in ``[0.0, 0.2]``.  Zero if there is not enough
            corroboration.
        """
        if direction == ImpactDirection.NEUTRAL:
            return 0.0

        try:
            recent = storage.get_analyses_for_ticker(ticker, limit=lookback_limit)
        except Exception as exc:
            logger.warning("Corroboration check failed for %s: %s", ticker, exc)
            return 0.0

        # Count distinct sources that agree
        agreeing_sources: set[str] = set()
        for item in recent:
            if item.get("impact_direction") == direction.value:
                agreeing_sources.add(item.get("source", ""))

        if len(agreeing_sources) < _MIN_CORROBORATING_SOURCES:
            return 0.0

        # Scale linearly: 2 sources → 0.1, 3 → 0.15, 4+ → 0.2
        bonus = min(
            _MAX_CORROBORATION_BONUS,
            0.05 * len(agreeing_sources),
        )
        logger.info(
            "Corroboration bonus for %s (%s): +%.2f from %d sources",
            ticker,
            direction.value,
            bonus,
            len(agreeing_sources),
        )
        return round(bonus, 4)

    @staticmethod
    def should_alert(score: float) -> bool:
        """Return ``True`` if *score* meets the alert threshold.

        Threshold is defined by :const:`IMPACT_ALERT_THRESHOLD` in
        ``src.shared.constants`` (default 0.7).

        Parameters
        ----------
        score:
            Final composite score (after corroboration bonus).

        Returns
        -------
        bool
        """
        return score >= IMPACT_ALERT_THRESHOLD

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_source_weight(source: DataSource) -> float:
        """Look up the source reliability weight from constants."""
        return SOURCE_WEIGHTS.get(source.value, 0.5)

    @staticmethod
    def _recency_factor(created_at: datetime) -> float:
        """Exponential decay factor: 1.0 today → 0.5 at 7 days.

        .. math::

            f = 2^{-\\Delta / T_{1/2}}

        where :math:`\\Delta` is age in days and :math:`T_{1/2}` = 7.
        """
        now = datetime.utcnow()
        # Ensure both datetimes are naive-UTC for consistent comparison
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)

        age_days = max(0.0, (now - created_at).total_seconds() / 86_400)
        factor = math.pow(2, -age_days / _RECENCY_HALF_LIFE_DAYS)
        return round(factor, 6)
