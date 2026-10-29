"""Market metrics data class for volatility analysis."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class MarketMetrics:
    """Aggregated market metrics for regime detection.

    Attributes:
        btc_price: Current BTC spot price.
        dvol: Deribit Volatility Index.
        iv_rank: IV Rank (0-1, current IV position in 52-week range).
        iv_percentile: IV Percentile (0-1, % of days below current IV).
        rv_7d: 7-day realized volatility (annualized %).
        rv_30d: 30-day realized volatility (annualized %).
        iv_rv_spread: DVOL minus 30-day RV (volatility points).
        term_structure_ratio: Near-term IV / Far-term IV.
        rr_skew: Risk reversal skew (25d call IV - 25d put IV).
        timestamp: When these metrics were calculated.
    """

    btc_price: float
    timestamp: datetime
    dvol: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    rv_7d: Optional[float] = None
    rv_30d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    term_structure_ratio: Optional[float] = None
    rr_skew: Optional[float] = None

    @property
    def calculated_iv_rv_spread(self) -> Optional[float]:
        """Calculate IV-RV spread from DVOL and 30d RV."""
        if self.dvol is not None and self.rv_30d is not None:
            return self.dvol - self.rv_30d
        return None

    @property
    def is_high_iv(self) -> bool:
        """Check if currently in high IV environment.

        High IV defined as: IV Rank > 50% AND IV-RV spread > 15 points.
        """
        if self.iv_rank is None:
            return False
        spread = self.iv_rv_spread or self.calculated_iv_rv_spread or 0
        return self.iv_rank > 0.5 and spread > 15

    @property
    def is_low_iv(self) -> bool:
        """Check if currently in low IV environment.

        Low IV defined as: IV Rank < 30% AND IV-RV spread < -10 points.
        """
        if self.iv_rank is None:
            return False
        spread = self.iv_rv_spread or self.calculated_iv_rv_spread or 0
        return self.iv_rank < 0.3 and spread < -10
