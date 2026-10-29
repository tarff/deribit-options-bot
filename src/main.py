"""Entry point for the crypto options trading bot."""

import asyncio
import logging
from pathlib import Path

from src.config import load_settings
from src.persistence.database import Database
from src.persistence.repositories import SnapshotRepository
from src.persistence.models import MarketSnapshot
from src.data.deribit_client import DeribitClient
from src.data.market_analyzer import MarketAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    logger.info("Crypto Options Bot starting...")

    # Load configuration
    config_path = Path("config/settings.yaml")
    if not config_path.exists():
        logger.warning("No config/settings.yaml found, using defaults")
    settings = load_settings(config_path if config_path.exists() else None)

    # Initialize database
    logger.info(f"Initializing database at {settings.database.path}")
    db = Database(settings.database.path)
    db.initialize()
    logger.info("Database initialized")

    # Initialize Deribit client
    client = DeribitClient(
        base_url=settings.deribit.base_url,
        api_key=settings.deribit.api_key,
        api_secret=settings.deribit.api_secret,
    )

    # Initialize market analyzer with configured currency
    currency = settings.trading.currency
    analyzer = MarketAnalyzer(client, currency=currency)
    snapshot_repo = SnapshotRepository(db)

    try:
        # Perform market analysis
        logger.info("Analyzing market conditions...")
        result = await analyzer.analyze()

        metrics = result["metrics"]
        regime = result["regime"]
        recommendation = result["recommendation"]

        # Log results
        logger.info(f"{currency} Price: ${metrics.btc_price:,.2f}")
        logger.info(f"DVOL: {metrics.dvol:.1f}")
        logger.info(f"IV Rank: {metrics.iv_rank:.1%}" if metrics.iv_rank else "IV Rank: N/A")
        logger.info(f"RV (30d): {metrics.rv_30d:.1f}%" if metrics.rv_30d else "RV (30d): N/A")
        logger.info(f"IV-RV Spread: {metrics.iv_rv_spread:.1f}" if metrics.iv_rv_spread else "IV-RV Spread: N/A")
        logger.info(f"Market Regime: {regime.value}")
        logger.info(f"Recommended Strategy: {recommendation.strategy or 'NONE'}")
        logger.info(f"Action: {recommendation.action}")
        logger.info(f"Reason: {recommendation.reason}")

        # Persist snapshot
        snapshot_repo.save(MarketSnapshot(
            btc_price=metrics.btc_price,
            dvol=metrics.dvol,
            iv_rank=metrics.iv_rank,
            iv_percentile=metrics.iv_percentile,
            rv_7d=metrics.rv_7d,
            rv_30d=metrics.rv_30d,
            iv_rv_spread=metrics.iv_rv_spread,
            regime=regime.value,
            active_strategy=recommendation.strategy,
            timestamp=metrics.timestamp,
        ))
        logger.info("Market snapshot saved to database")

        logger.info("Phase 2 complete. Ready for Phase 3 (Strategy Implementation).")

    except Exception as e:
        logger.error(f"Error during market analysis: {e}")
        raise
    finally:
        await client.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
