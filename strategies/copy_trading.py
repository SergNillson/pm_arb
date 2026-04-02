"""
Copy Trading strategy (basic scaffolding).

Monitors a list of top-performing wallets on Polymarket and mirrors
their trades with configurable delay and size scaling.

NOTE: This module provides the foundation for copy trading.  Full
on-chain event streaming and wallet-resolution logic should be added
once the other strategies are stable.
"""

import asyncio
import logging
from typing import Dict, List, Optional

import aiohttp

from config import Config
from exchanges.polymarket import PolymarketClient
from risk_manager import RiskManager
from utils.database import Database

logger = logging.getLogger("polymarket_bot")

# Polymarket GraphQL / data API endpoints (public)
POLYMARKET_DATA_API = "https://data-api.polymarket.com"

# Wallets to follow (can be extended via config)
DEFAULT_WATCHED_WALLETS: List[str] = []


class CopyTrader:
    """
    Copy-trading strategy: follows trades made by monitored wallets.

    For each detected trade the strategy decides whether to copy it
    based on the current risk limits and position sizing rules.
    """

    def __init__(
        self,
        config: Config,
        polymarket: PolymarketClient,
        risk_manager: RiskManager,
        database: Database,
        watched_wallets: Optional[List[str]] = None,
    ):
        self.config = config
        self.polymarket = polymarket
        self.risk_manager = risk_manager
        self.db = database
        self.watched_wallets: List[str] = watched_wallets or DEFAULT_WATCHED_WALLETS

        self.running = False
        # wallet -> last seen trade timestamp
        self._last_seen: Dict[str, int] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def start(self) -> None:
        """Start the copy-trading polling loop."""
        if not self.watched_wallets:
            logger.warning("Copy Trading: no wallets configured – strategy idle")
            return

        self.running = True
        logger.info("Copy Trading strategy started, watching %d wallets", len(self.watched_wallets))

        while self.running:
            try:
                await self._poll_wallets()
            except Exception as exc:
                logger.error("Copy trading poll error: %s", exc)
            await asyncio.sleep(15)

    def stop(self) -> None:
        self.running = False
        logger.info("Copy Trading strategy stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _poll_wallets(self) -> None:
        """Check each watched wallet for new trades."""
        for wallet in self.watched_wallets:
            trades = await self._fetch_recent_trades(wallet)
            for trade in trades:
                trade_ts = trade.get("timestamp", 0)
                if trade_ts > self._last_seen.get(wallet, 0):
                    await self._copy_trade(wallet, trade)
            if trades:
                self._last_seen[wallet] = max(
                    t.get("timestamp", 0) for t in trades
                )

    async def _fetch_recent_trades(self, wallet: str) -> List[Dict]:
        """Return the most recent trades for a wallet from the data API."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{POLYMARKET_DATA_API}/activity",
                params={"user": wallet, "limit": 10},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as exc:
            logger.debug("Copy trader fetch error for %s: %s", wallet[:10], exc)
            return []

    async def _copy_trade(self, wallet: str, trade: Dict) -> None:
        """Mirror a trade from a watched wallet."""
        market_id = trade.get("market", trade.get("conditionId", ""))
        outcome = trade.get("outcome", "YES").upper()
        original_amount = float(trade.get("amount", 0))

        if original_amount <= 0:
            return

        balance = await self.polymarket.get_balance()
        can_trade, reason = self.risk_manager.can_open_position(balance)
        if not can_trade:
            logger.info("Copy trade blocked for %s: %s", wallet[:10], reason)
            return

        # Scale size to our risk parameters
        scaled_amount = min(
            original_amount,
            balance * (self.config.MAX_RISK_PER_TRADE / 100),
        )

        logger.info(
            "COPY TRADE | wallet=%s | market=%s | %s | $%.2f",
            wallet[:10], market_id[:12], outcome, scaled_amount,
        )

        token_id = trade.get("token_id", market_id)
        result = await self.polymarket.place_market_order(token_id, "BUY", scaled_amount)
        if result:
            self.risk_manager.register_open_position(token_id)
            self.db.add_trade({
                "market_id": market_id,
                "asset": trade.get("asset", "UNKNOWN"),
                "direction": outcome,
                "entry_price": float(trade.get("price", 0.5)),
                "size": scaled_amount,
                "strategy": "copy_trading",
                "paper": int(self.config.PAPER_TRADING),
            })
