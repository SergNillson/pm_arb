"""
Latency Arbitrage strategy.

Monitors real-time spot prices on centralised exchanges (Binance, Bybit,
Coinbase) and detects when Polymarket binary Up/Down market prices lag
behind the actual spot price movement.  Enters a trade when the detected
edge exceeds the configured minimum threshold.
"""

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional

from config import Config
from exchanges.polymarket import PolymarketClient
from risk_manager import RiskManager
from utils.calculator import calculate_edge, calculate_position_size
from utils.database import Database

logger = logging.getLogger("polymarket_bot")

# Time frames mapped to approximate resolution windows in seconds
TIME_FRAMES: Dict[str, int] = {
    "5min": 300,
    "15min": 900,
    "1hour": 3600,
}


class LatencyArbitrage:
    """
    Latency arbitrage strategy implementation.

    For each monitored asset, the strategy:
    1. Receives the latest spot prices from centralised exchanges.
    2. Fetches the current YES price from Polymarket short-term markets.
    3. Computes the theoretical correct probability of the price going UP.
    4. If the edge (theoretical probability - Polymarket price) >= threshold,
       places a BUY YES order.
    5. If the inverse edge is large enough, places a BUY NO order.
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

        # asset -> latest spot price (averaged across exchanges)
        self._spot_prices: Dict[str, float] = {}
        # asset -> previous spot price snapshot
        self._prev_prices: Dict[str, float] = {}
        # asset + timeframe -> polymarket market info cache
        self._markets_cache: List[Dict] = []

        self.running = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the strategy loop."""
        self.running = True
        logger.info("Latency Arbitrage strategy started")
        await self._refresh_markets()
        while self.running:
            try:
                await self._run_cycle()
            except Exception as exc:
                logger.error("Latency arb cycle error: %s", exc)
            await asyncio.sleep(1)

    def stop(self) -> None:
        """Stop the strategy loop."""
        self.running = False
        logger.info("Latency Arbitrage strategy stopped")

    def update_spot_price(self, asset: str, price: float) -> None:
        """Receive a new spot price update from an exchange feed."""
        if asset.upper() in self.config.ASSETS:
            prev = self._spot_prices.get(asset.upper())
            if prev:
                self._prev_prices[asset.upper()] = prev
            self._spot_prices[asset.upper()] = price

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _refresh_markets(self) -> None:
        """Refresh the list of active short-term Polymarket markets."""
        markets = await self.polymarket.get_markets(active=True, limit=500)
        self._markets_cache = self._filter_relevant_markets(markets)
        logger.info("Cached %d relevant Polymarket markets", len(self._markets_cache))

    def _filter_relevant_markets(self, markets: List[Dict]) -> List[Dict]:
        """Keep only short-term Up/Down crypto markets for monitored assets."""
        result = []
        for market in markets:
            question = market.get("question", "").lower()
            # Only consider up/down binary markets
            if not any(kw in question for kw in ("up", "down", "above", "below", "higher", "lower")):
                continue
            # Only consider monitored assets
            if not any(asset.lower() in question for asset in self.config.ASSETS):
                continue
            result.append(market)
        return result

    def _get_asset_from_market(self, market: Dict) -> Optional[str]:
        question = market.get("question", "").lower()
        for asset in self.config.ASSETS:
            if asset.lower() in question:
                return asset.upper()
        return None

    def _infer_probability_from_spot(self, asset: str) -> Optional[float]:
        """
        Convert spot price movement into a binary UP probability estimate.

        Uses a simple momentum heuristic:
        - If price moved up significantly → high UP probability
        - If price moved down significantly → low UP probability
        - Flat movement → ~0.5
        """
        current = self._spot_prices.get(asset)
        previous = self._prev_prices.get(asset)
        if current is None or previous is None or previous == 0:
            return None

        change_pct = (current - previous) / previous * 100

        # Map change percentage to probability using a sigmoid-like curve
        # change_pct of ±2% maps to ~0.75/0.25
        k = 3.0  # sensitivity
        probability = 1 / (1 + math.exp(-k * change_pct))
        return round(probability, 4)

    async def _run_cycle(self) -> None:
        """Execute one arbitrage scan cycle."""
        if not self._spot_prices:
            return

        # Refresh markets every 5 minutes
        if not hasattr(self, "_last_market_refresh"):
            self._last_market_refresh = 0
        now = time.time()
        if now - self._last_market_refresh > 300:
            await self._refresh_markets()
            self._last_market_refresh = now

        for market in self._markets_cache:
            if not self.running:
                break
            await self._evaluate_market(market)

    async def _evaluate_market(self, market: Dict) -> None:
        """Evaluate a single market for an arbitrage opportunity."""
        asset = self._get_asset_from_market(market)
        if not asset:
            return

        theoretical_prob = self._infer_probability_from_spot(asset)
        if theoretical_prob is None:
            return

        # Get YES token ID (first token in the list)
        tokens = market.get("tokens", [])
        yes_token = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), None)
        if not yes_token:
            return

        token_id = yes_token.get("token_id")
        if not token_id:
            return

        polymarket_price = await self.polymarket.get_market_price(token_id)
        if polymarket_price is None:
            return

        # Calculate edges for YES and NO
        yes_edge = calculate_edge(theoretical_prob, polymarket_price, "YES")
        no_edge = calculate_edge(theoretical_prob, polymarket_price, "NO")

        min_edge = self.config.MIN_EDGE_PERCENTAGE

        if yes_edge >= min_edge:
            await self._execute_trade(market, token_id, "YES", yes_edge, polymarket_price, asset)
        elif no_edge >= min_edge:
            # For NO, we trade the NO token
            no_token = next((t for t in tokens if t.get("outcome", "").upper() == "NO"), None)
            if no_token:
                await self._execute_trade(
                    market, no_token["token_id"], "NO", no_edge, 1 - polymarket_price, asset
                )

    async def _execute_trade(
        self,
        market: Dict,
        token_id: str,
        direction: str,
        edge: float,
        price: float,
        asset: str,
    ) -> None:
        """Check risk limits and place an order."""
        balance = await self.polymarket.get_balance()

        # Risk manager checks
        can_trade, reason = self.risk_manager.can_open_position(balance)
        if not can_trade:
            logger.info("Risk block on %s (%s): %s", market.get("question", "?"), direction, reason)
            return

        size = calculate_position_size(balance, self.config.MAX_RISK_PER_TRADE, price)

        logger.info(
            "ARB SIGNAL | %s | %s | edge=%.2f%% | price=%.4f | size=$%.2f",
            asset,
            direction,
            edge,
            price,
            size,
        )

        result = await self.polymarket.place_market_order(token_id, "BUY", size)
        if result:
            self.risk_manager.register_open_position(token_id)
            self.db.add_trade({
                "market_id": market.get("market_slug", token_id),
                "asset": asset,
                "direction": direction,
                "entry_price": price,
                "size": size,
                "strategy": "latency_arbitrage",
                "paper": int(self.config.PAPER_TRADING),
            })
            logger.info("Order placed: %s", result)
