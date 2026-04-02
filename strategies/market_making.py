"""
Market Making strategy.

Places limit orders on both sides of the order book to earn rebates
and the bid-ask spread.  Automatically adjusts quotes when the market
moves beyond configurable thresholds.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from config import Config
from exchanges.polymarket import PolymarketClient
from risk_manager import RiskManager
from utils.database import Database

logger = logging.getLogger("polymarket_bot")

# Default spread around mid price (in probability units, i.e. 0-1)
DEFAULT_SPREAD = 0.02
# Minimum order size in USD
MIN_ORDER_SIZE = 5.0
# How often to refresh quotes (seconds)
QUOTE_REFRESH_INTERVAL = 10


class MarketMaker:
    """
    Market-making strategy for Polymarket binary markets.

    For each selected market the strategy maintains a pair of resting limit
    orders (one BUY, one SELL) symmetrically around the current mid price.
    Orders are refreshed whenever the mid price drifts beyond half the spread.
    """

    def __init__(
        self,
        config: Config,
        polymarket: PolymarketClient,
        risk_manager: RiskManager,
        database: Database,
    ):
        self.config = config
        self.polymarket = polymarket
        self.risk_manager = risk_manager
        self.db = database

        self.running = False
        # token_id -> {"buy": order_id, "sell": order_id, "mid": float}
        self._active_quotes: Dict[str, Dict] = {}
        self._markets: List[Dict] = []

    async def start(self) -> None:
        """Start the market-making loop."""
        self.running = True
        logger.info("Market Making strategy started")
        await self._load_markets()
        while self.running:
            try:
                await self._run_cycle()
            except Exception as exc:
                logger.error("Market making cycle error: %s", exc)
            await asyncio.sleep(QUOTE_REFRESH_INTERVAL)

    def stop(self) -> None:
        """Stop the market-making loop and cancel all open quotes."""
        self.running = False
        logger.info("Market Making strategy stopped")

    async def _load_markets(self) -> None:
        """Load a curated list of liquid markets to quote."""
        markets = await self.polymarket.get_markets(active=True, limit=200)
        # Focus on crypto Up/Down markets for the configured assets
        self._markets = [
            m for m in markets
            if any(a.lower() in m.get("question", "").lower() for a in self.config.ASSETS)
            and any(
                kw in m.get("question", "").lower()
                for kw in ("up", "down", "above", "below", "higher", "lower")
            )
        ][:20]  # Cap at 20 markets to avoid spreading too thin
        logger.info("Market maker loaded %d markets", len(self._markets))

    async def _run_cycle(self) -> None:
        """Refresh quotes for all markets in the portfolio."""
        balance = await self.polymarket.get_balance()
        order_size = max(
            MIN_ORDER_SIZE,
            balance * (self.config.MAX_RISK_PER_TRADE / 100) / 2,
        )

        for market in self._markets:
            if not self.running:
                break
            await self._update_quotes(market, order_size)

    async def _update_quotes(self, market: Dict, order_size: float) -> None:
        """Place or refresh quotes for a single market."""
        tokens = market.get("tokens", [])
        yes_token = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), None)
        if not yes_token:
            return

        token_id = yes_token.get("token_id", "")
        mid_price = await self.polymarket.get_market_price(token_id)
        if mid_price is None:
            return

        existing = self._active_quotes.get(token_id, {})
        prev_mid = existing.get("mid")

        # Only refresh if mid has moved more than half the spread
        if prev_mid and abs(mid_price - prev_mid) < DEFAULT_SPREAD / 2:
            logger.debug("MM skipping %s: mid unchanged (%.4f)", token_id[:12], mid_price)
            return

        # Cancel old quotes
        for side in ("buy", "sell"):
            old_oid = existing.get(side)
            if old_oid:
                await self.polymarket.cancel_order(old_oid)

        # Ensure spread boundaries are valid (0 < bid < ask < 1)
        bid = round(max(0.01, mid_price - DEFAULT_SPREAD / 2), 4)
        ask = round(min(0.99, mid_price + DEFAULT_SPREAD / 2), 4)
        if bid >= ask:
            return

        can_trade, reason = self.risk_manager.can_open_position(
            await self.polymarket.get_balance()
        )
        if not can_trade:
            logger.debug("Market maker skipping %s: %s", token_id[:8], reason)
            return

        buy_result = await self.polymarket.place_limit_order(token_id, "BUY", bid, order_size)
        sell_result = await self.polymarket.place_limit_order(token_id, "SELL", ask, order_size)

        self._active_quotes[token_id] = {
            "buy": buy_result.get("order_id") if buy_result else None,
            "sell": sell_result.get("order_id") if sell_result else None,
            "mid": mid_price,
        }

        logger.debug(
            "MM quotes updated | %s | bid=%.4f ask=%.4f size=%.2f",
            token_id[:12], bid, ask, order_size,
        )

    async def cancel_all_quotes(self) -> None:
        """Cancel every open quote (used during graceful shutdown)."""
        logger.info("Cancelling all market maker quotes...")
        for token_id, quotes in self._active_quotes.items():
            for side in ("buy", "sell"):
                oid = quotes.get(side)
                if oid:
                    await self.polymarket.cancel_order(oid)
        self._active_quotes.clear()
        logger.info("All quotes cancelled")
