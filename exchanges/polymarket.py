"""Polymarket CLOB API integration."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp
import websockets

logger = logging.getLogger("polymarket_bot")

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PolymarketClient:
    """
    Client for interacting with the Polymarket CLOB API.

    Supports fetching markets, placing/cancelling orders, and
    retrieving balances. WebSocket is used for real-time order book updates.
    """

    def __init__(self, api_key: str, private_key: str, wallet_address: str, paper: bool = True):
        self.api_key = api_key
        self.private_key = private_key
        self.wallet_address = wallet_address
        self.paper = paper
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
        return self.session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_markets(self, active: bool = True, limit: int = 100) -> List[Dict]:
        """Return a list of markets from the CLOB API."""
        session = await self._get_session()
        params: Dict[str, Any] = {"active": active, "limit": limit}
        try:
            async with session.get(f"{POLYMARKET_CLOB_URL}/markets", params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("data", [])
        except Exception as exc:
            logger.error("Failed to fetch markets: %s", exc)
            return []

    async def get_order_book(self, token_id: str) -> Dict:
        """Return the current order book for a given token ID."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{POLYMARKET_CLOB_URL}/book", params={"token_id": token_id}
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as exc:
            logger.error("Failed to fetch order book for %s: %s", token_id, exc)
            return {}

    async def get_market_price(self, token_id: str) -> Optional[float]:
        """Return the mid price for a given token."""
        book = await self.get_order_book(token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if bids and asks:
            best_bid = float(bids[0]["price"])
            best_ask = float(asks[0]["price"])
            return round((best_bid + best_ask) / 2, 4)
        return None

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    async def get_balance(self) -> float:
        """Return USDC balance for the configured wallet."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{POLYMARKET_CLOB_URL}/balance",
                params={"address": self.wallet_address},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return float(data.get("balance", 0))
        except Exception as exc:
            logger.error("Failed to fetch balance: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    async def place_market_order(
        self,
        token_id: str,
        side: str,
        amount: float,
    ) -> Optional[Dict]:
        """
        Place a market order.

        Args:
            token_id: The Polymarket outcome token ID.
            side: "BUY" or "SELL".
            amount: Amount in USDC to trade.

        Returns:
            Order response dict, or None on failure.
        """
        if self.paper:
            logger.info("[PAPER] Market order: %s %s %.2f USDC", side, token_id, amount)
            return {"order_id": "paper_" + token_id[:8], "status": "MATCHED"}

        session = await self._get_session()
        payload = {
            "token_id": token_id,
            "side": side,
            "amount_usdc": amount,
            "type": "MARKET",
        }
        try:
            async with session.post(
                f"{POLYMARKET_CLOB_URL}/order", json=payload
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as exc:
            logger.error("Failed to place market order: %s", exc)
            return None

    async def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Optional[Dict]:
        """
        Place a limit order in the CLOB.

        Args:
            token_id: Outcome token ID.
            side: "BUY" or "SELL".
            price: Limit price (0-1).
            size: Number of shares.

        Returns:
            Order response dict, or None on failure.
        """
        if self.paper:
            logger.info(
                "[PAPER] Limit order: %s %s @ %.4f x %.2f shares",
                side, token_id, price, size,
            )
            return {"order_id": "paper_lim_" + token_id[:8], "status": "LIVE"}

        session = await self._get_session()
        payload = {
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": size,
            "type": "LIMIT",
        }
        try:
            async with session.post(
                f"{POLYMARKET_CLOB_URL}/order", json=payload
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as exc:
            logger.error("Failed to place limit order: %s", exc)
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by its ID."""
        if self.paper:
            logger.info("[PAPER] Cancel order: %s", order_id)
            return True

        session = await self._get_session()
        try:
            async with session.delete(
                f"{POLYMARKET_CLOB_URL}/order/{order_id}"
            ) as resp:
                resp.raise_for_status()
                return True
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", order_id, exc)
            return False

    async def get_positions(self) -> List[Dict]:
        """Return open positions for the configured wallet."""
        session = await self._get_session()
        try:
            async with session.get(
                f"{POLYMARKET_CLOB_URL}/positions",
                params={"address": self.wallet_address},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("data", [])
        except Exception as exc:
            logger.error("Failed to fetch positions: %s", exc)
            return []

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def subscribe_order_book(self, token_id: str, callback) -> None:
        """
        Subscribe to real-time order book updates via WebSocket.

        Args:
            token_id: Outcome token ID to subscribe to.
            callback: Async callable that receives parsed message dicts.
        """
        url = f"{POLYMARKET_WS_URL}/{token_id}"
        logger.info("Connecting to Polymarket WS for token %s", token_id)
        try:
            async with websockets.connect(url) as ws:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await callback(msg)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from Polymarket WS: %s", raw[:100])
        except Exception as exc:
            logger.error("Polymarket WS error for %s: %s", token_id, exc)
