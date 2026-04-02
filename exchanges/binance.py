"""Binance exchange integration for real-time price monitoring."""

import asyncio
import json
import logging
from typing import Callable, Dict, Optional

import aiohttp
import websockets

logger = logging.getLogger("polymarket_bot")

BINANCE_REST_URL = "https://api.binance.com"
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

# Mapping from asset symbol to Binance trading pair
SYMBOL_MAP: Dict[str, str] = {
    "BTC": "btcusdt",
    "ETH": "ethusdt",
    "SOL": "solusdt",
    "XRP": "xrpusdt",
}


class BinanceClient:
    """Read-only client for Binance price data (REST + WebSocket)."""

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self._prices: Dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {}
            if self.api_key:
                headers["X-MBX-APIKEY"] = self.api_key
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_price(self, asset: str) -> Optional[float]:
        """Fetch the latest price for the given asset via REST."""
        symbol = SYMBOL_MAP.get(asset.upper())
        if not symbol:
            logger.warning("Binance: unknown asset %s", asset)
            return None

        session = await self._get_session()
        try:
            async with session.get(
                f"{BINANCE_REST_URL}/api/v3/ticker/price",
                params={"symbol": symbol.upper()},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                price = float(data["price"])
                self._prices[asset.upper()] = price
                return price
        except Exception as exc:
            logger.error("Binance REST error for %s: %s", asset, exc)
            return None

    def get_cached_price(self, asset: str) -> Optional[float]:
        """Return the most recently received price for the given asset."""
        return self._prices.get(asset.upper())

    async def stream_prices(self, assets: list, callback: Callable) -> None:
        """
        Stream real-time prices for given assets via WebSocket.

        Args:
            assets: List of asset symbols e.g. ["BTC", "ETH"].
            callback: Async callable(asset: str, price: float).
        """
        streams = [f"{SYMBOL_MAP[a.upper()]}@miniTicker" for a in assets if a.upper() in SYMBOL_MAP]
        if not streams:
            logger.warning("Binance: no valid assets to stream")
            return

        url = f"{BINANCE_WS_URL}/{'/'.join(streams)}"
        logger.info("Connecting to Binance WebSocket: %s", url)

        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            # Combined stream wraps messages in {"stream":..., "data":...}
                            data = msg.get("data", msg)
                            symbol = data.get("s", "")
                            close_price = float(data.get("c", 0))
                            if close_price > 0:
                                asset = next(
                                    (k for k, v in SYMBOL_MAP.items() if v == symbol.lower()),
                                    None,
                                )
                                if asset:
                                    self._prices[asset] = close_price
                                    await callback(asset, close_price)
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            logger.warning("Binance WS parse error: %s", exc)
            except Exception as exc:
                logger.error("Binance WS disconnected: %s – reconnecting in 5s", exc)
                await asyncio.sleep(5)
