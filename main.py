"""
Polymarket Trading Bot – main entry point.

Usage:
    python main.py

The bot reads configuration from a .env file (see .env.example),
initialises all strategy and exchange components, then runs an async
event loop until interrupted with Ctrl+C.
"""

import asyncio
import logging
import signal
import sys

from config import config
from exchanges.binance import BinanceClient
from exchanges.bybit import BybitClient
from exchanges.coinbase import CoinbaseClient
from exchanges.polymarket import PolymarketClient
from risk_manager import RiskManager
from strategies.copy_trading import CopyTrader
from strategies.latency_arbitrage import LatencyArbitrage
from strategies.market_making import MarketMaker
from telegram_bot import TelegramInterface
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger("polymarket_bot")


class TradingBot:
    """
    Orchestrates all bot components and strategies.

    Responsibilities:
    - Initialise exchange clients and database.
    - Start / stop strategy loops.
    - Feed real-time price updates to active strategies.
    - Handle graceful shutdown on SIGINT / SIGTERM.
    """

    def __init__(self):
        self.config = config
        self.running = False

        # Core services
        self.db = Database()
        self.risk_manager = RiskManager(
            max_open_positions=config.MAX_OPEN_POSITIONS,
            daily_loss_limit_pct=config.DAILY_LOSS_LIMIT,
            max_risk_per_trade_pct=config.MAX_RISK_PER_TRADE,
            database=self.db,
        )

        # Exchange clients
        self.polymarket = PolymarketClient(
            api_key=config.POLYMARKET_API_KEY,
            private_key=config.POLYMARKET_PRIVATE_KEY,
            wallet_address=config.POLYMARKET_WALLET_ADDRESS,
            paper=config.PAPER_TRADING,
        )
        self.binance = BinanceClient(
            api_key=config.BINANCE_API_KEY,
            secret_key=config.BINANCE_SECRET_KEY,
        )
        self.bybit = BybitClient(
            api_key=config.BYBIT_API_KEY,
            secret_key=config.BYBIT_SECRET_KEY,
        )
        self.coinbase = CoinbaseClient(
            api_key=config.COINBASE_API_KEY,
            secret_key=config.COINBASE_SECRET_KEY,
        )

        # Strategies
        self.latency_arb = LatencyArbitrage(config, self.polymarket, self.risk_manager, self.db)
        self.market_maker = MarketMaker(config, self.polymarket, self.risk_manager, self.db)
        self.copy_trader = CopyTrader(config, self.polymarket, self.risk_manager, self.db)

        # Telegram interface
        self.telegram = TelegramInterface(
            token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID,
            bot=self,
        )

    # ------------------------------------------------------------------
    # Exchange price callback
    # ------------------------------------------------------------------

    async def _on_price_update(self, asset: str, price: float) -> None:
        """Receive a real-time price update and propagate to strategies."""
        if config.ENABLE_LATENCY_ARBITRAGE:
            self.latency_arb.update_spot_price(asset, price)

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start all components and enter the main event loop."""
        self.running = True
        mode = "PAPER TRADING" if config.PAPER_TRADING else "LIVE TRADING"
        logger.info("=" * 60)
        logger.info("  Polymarket Trading Bot  –  %s", mode)
        logger.info("=" * 60)
        logger.info("Assets: %s", config.ASSETS)
        logger.info("Strategies: latency_arb=%s  market_making=%s  copy_trading=%s",
                    config.ENABLE_LATENCY_ARBITRAGE,
                    config.ENABLE_MARKET_MAKING,
                    config.ENABLE_COPY_TRADING)

        # Validate config (raises on missing keys in live mode)
        config.validate()

        tasks = []

        # Telegram bot
        tasks.append(asyncio.create_task(self.telegram.start(), name="telegram"))

        # Price WebSocket streams (all in parallel)
        tasks.append(asyncio.create_task(
            self.binance.stream_prices(config.ASSETS, self._on_price_update),
            name="binance_ws",
        ))
        tasks.append(asyncio.create_task(
            self.bybit.stream_prices(config.ASSETS, self._on_price_update),
            name="bybit_ws",
        ))
        tasks.append(asyncio.create_task(
            self.coinbase.stream_prices(config.ASSETS, self._on_price_update),
            name="coinbase_ws",
        ))

        # Strategy loops
        if config.ENABLE_LATENCY_ARBITRAGE:
            tasks.append(asyncio.create_task(self.latency_arb.start(), name="latency_arb"))

        if config.ENABLE_MARKET_MAKING:
            tasks.append(asyncio.create_task(self.market_maker.start(), name="market_making"))

        if config.ENABLE_COPY_TRADING:
            tasks.append(asyncio.create_task(self.copy_trader.start(), name="copy_trading"))

        # Notify via Telegram
        await self.telegram.notify(
            f"🤖 <b>Trading bot started</b>\nMode: {mode}\nAssets: {', '.join(config.ASSETS)}"
        )

        logger.info("All components running. Press Ctrl+C to stop.")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def shutdown(self) -> None:
        """Gracefully shut down all components."""
        if not self.running:
            return

        self.running = False
        logger.info("Shutting down trading bot...")

        self.latency_arb.stop()
        self.market_maker.stop()
        self.copy_trader.stop()

        # Cancel all market maker quotes
        if config.ENABLE_MARKET_MAKING:
            await self.market_maker.cancel_all_quotes()

        await self.telegram.notify("🛑 <b>Trading bot stopped</b>")
        await self.telegram.stop()

        await self.polymarket.close()
        await self.binance.close()
        await self.bybit.close()
        await self.coinbase.close()

        logger.info("Shutdown complete")


def _install_signal_handlers(bot: TradingBot, loop: asyncio.AbstractEventLoop) -> None:
    """Register SIGINT/SIGTERM handlers for graceful shutdown."""

    def _handle_signal():
        logger.info("Signal received, initiating shutdown...")
        loop.create_task(bot.shutdown())
        # Cancel all running tasks after a short delay
        loop.call_later(3, loop.stop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass


def main() -> None:
    """Entry point: create the bot and run the event loop."""
    bot = TradingBot()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(bot, loop)
    try:
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        loop.run_until_complete(bot.shutdown())
        loop.close()
        logger.info("Event loop closed. Goodbye!")


if __name__ == "__main__":
    main()
