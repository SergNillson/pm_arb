"""Coinbase Advanced Trade API integration for real-time price monitoring."""

import asyncio
import json
import logging
from typing import Callable, Dict, Optional

import aiohttp
import websockets

logger = logging.getLogger("polymarket_bot")

COINBASE_REST_URL = "https://api.coinbase.com/api/v3/brokerage"
COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"

SYMBOL_MAP: Dict[str, str] = {
    "BTC": "BTC-USDC",
    "ETH": "ETH-USDC",
    "SOL": "SOL-USDC",
    "XRP": "XRP-USDC",
}


class CoinbaseClient:
    """Read-only client for Coinbase Advanced Trade price data."""

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self._prices: Dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {}
            if self.api_key:
                headers["CB-ACCESS-KEY"] = self.api_key
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_price(self, asset: str) -> Optional[float]:
        """Fetch the latest price for an asset via REST."""
        product_id = SYMBOL_MAP.get(asset.upper())
        if not product_id:
            logger.warning("Coinbase: unknown asset %s", asset)
            return None

        session = await self._get_session()
        try:
            async with session.get(
                f"{COINBASE_REST_URL}/market/products/{product_id}/ticker",
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                price = float(data.get("price", 0))
                if price > 0:
                    self._prices[asset.upper()] = price
                return price if price > 0 else None
        except Exception as exc:
            logger.error("Coinbase REST error for %s: %s", asset, exc)
            return None

    def get_cached_price(self, asset: str) -> Optional[float]:
        return self._prices.get(asset.upper())

    async def stream_prices(self, assets: list, callback: Callable) -> None:
        """
        Stream real-time ticker prices via WebSocket.

        Args:
            assets: List of asset symbols.
            callback: Async callable(asset: str, price: float).
        """
        product_ids = [SYMBOL_MAP[a.upper()] for a in assets if a.upper() in SYMBOL_MAP]
        if not product_ids:
            return

        subscribe_msg = {
            "type": "subscribe",
            "product_ids": product_ids,
            "channel": "ticker",
        }

        logger.info("Connecting to Coinbase WebSocket")
        while True:
            try:
                async with websockets.connect(COINBASE_WS_URL) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            if msg.get("channel") == "ticker":
                                for event in msg.get("events", []):
                                    for ticker in event.get("tickers", []):
                                        product_id = ticker.get("product_id", "")
                                        price_str = ticker.get("price", "0")
                                        price = float(price_str) if price_str else 0.0
                                        if price > 0:
                                            asset = next(
                                                (k for k, v in SYMBOL_MAP.items() if v == product_id),
                                                None,
                                            )
                                            if asset:
                                                self._prices[asset] = price
                                                await callback(asset, price)
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            logger.warning("Coinbase WS parse error: %s", exc)
            except Exception as exc:
                logger.error("Coinbase WS disconnected: %s – reconnecting in 5s", exc)
                await asyncio.sleep(5)
