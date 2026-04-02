"""Bybit exchange integration for real-time price monitoring."""

import asyncio
import json
import logging
from typing import Callable, Dict, Optional

import aiohttp
import websockets

logger = logging.getLogger("polymarket_bot")

BYBIT_REST_URL = "https://api.bybit.com"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/spot"

SYMBOL_MAP: Dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
}


class BybitClient:
    """Read-only client for Bybit price data (REST + WebSocket)."""

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self._prices: Dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_price(self, asset: str) -> Optional[float]:
        """Fetch the latest price for an asset via REST."""
        symbol = SYMBOL_MAP.get(asset.upper())
        if not symbol:
            logger.warning("Bybit: unknown asset %s", asset)
            return None

        session = await self._get_session()
        try:
            async with session.get(
                f"{BYBIT_REST_URL}/v5/market/tickers",
                params={"category": "spot", "symbol": symbol},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                price = float(data["result"]["list"][0]["lastPrice"])
                self._prices[asset.upper()] = price
                return price
        except Exception as exc:
            logger.error("Bybit REST error for %s: %s", asset, exc)
            return None

    def get_cached_price(self, asset: str) -> Optional[float]:
        return self._prices.get(asset.upper())

    async def stream_prices(self, assets: list, callback: Callable) -> None:
        """
        Stream real-time prices via WebSocket.

        Args:
            assets: List of asset symbols.
            callback: Async callable(asset: str, price: float).
        """
        symbols = [SYMBOL_MAP[a.upper()] for a in assets if a.upper() in SYMBOL_MAP]
        if not symbols:
            return

        subscribe_msg = {
            "op": "subscribe",
            "args": [f"tickers.{s}" for s in symbols],
        }

        logger.info("Connecting to Bybit WebSocket")
        while True:
            try:
                async with websockets.connect(BYBIT_WS_URL) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            if msg.get("topic", "").startswith("tickers."):
                                symbol = msg["data"].get("symbol", "")
                                last_price = msg["data"].get("lastPrice")
                                if last_price:
                                    price = float(last_price)
                                    asset = next(
                                        (k for k, v in SYMBOL_MAP.items() if v == symbol),
                                        None,
                                    )
                                    if asset:
                                        self._prices[asset] = price
                                        await callback(asset, price)
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            logger.warning("Bybit WS parse error: %s", exc)
            except Exception as exc:
                logger.error("Bybit WS disconnected: %s – reconnecting in 5s", exc)
                await asyncio.sleep(5)
