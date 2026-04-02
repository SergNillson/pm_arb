"""
Telegram Bot interface for managing and monitoring the trading bot.

Commands:
    /start      – Start the trading bot
    /stop       – Stop the trading bot
    /status     – Show bot status and open positions
    /balance    – Show current balance
    /stats      – Show performance statistics
    /risk       – Show current risk parameters
    /help       – Show available commands
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

if TYPE_CHECKING:
    from main import TradingBot

logger = logging.getLogger("polymarket_bot")


class TelegramInterface:
    """Telegram bot interface for controlling and monitoring the trading bot."""

    def __init__(self, token: str, chat_id: str, bot: Optional["TradingBot"] = None):
        self.token = token
        self.chat_id = chat_id
        self.trading_bot = bot
        self._app: Optional[Application] = None

    def set_trading_bot(self, bot: "TradingBot") -> None:
        """Link the Telegram interface to the running trading bot instance."""
        self.trading_bot = bot

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise and start the Telegram bot (non-blocking polling)."""
        if not self.token:
            logger.warning("Telegram bot token not configured – interface disabled")
            return

        self._app = Application.builder().token(self.token).build()
        self._register_handlers()
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        """Gracefully shut down the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    async def notify(self, message: str) -> None:
        """Send a message to the configured chat ID."""
        if not self._app or not self.chat_id:
            return
        try:
            await self._app.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to send Telegram message: %s", exc)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("stop", self._cmd_stop))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("balance", self._cmd_balance))
        self._app.add_handler(CommandHandler("stats", self._cmd_stats))
        self._app.add_handler(CommandHandler("risk", self._cmd_risk))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if self.trading_bot and not self.trading_bot.running:
            asyncio.create_task(self.trading_bot.run())
            await update.message.reply_text("✅ Trading bot started!")
        else:
            await update.message.reply_text("⚠️ Bot is already running.")

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if self.trading_bot and self.trading_bot.running:
            await self.trading_bot.shutdown()
            await update.message.reply_text("🛑 Trading bot stopped.")
        else:
            await update.message.reply_text("⚠️ Bot is not running.")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if not self.trading_bot:
            await update.message.reply_text("❌ Trading bot not initialised.")
            return

        risk_status = self.trading_bot.risk_manager.status()
        mode = "📄 Paper Trading" if self.trading_bot.config.PAPER_TRADING else "💸 Live Trading"
        msg = (
            f"<b>Bot Status</b>\n"
            f"Mode: {mode}\n"
            f"Running: {'✅' if self.trading_bot.running else '❌'}\n"
            f"Open positions: {risk_status['open_positions']} / {risk_status['max_open_positions']}\n"
        )
        await update.message.reply_text(msg)

    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if not self.trading_bot:
            await update.message.reply_text("❌ Trading bot not initialised.")
            return
        try:
            balance = await self.trading_bot.polymarket.get_balance()
            await update.message.reply_text(f"💰 Balance: <b>${balance:.2f} USDC</b>")
        except Exception as exc:
            await update.message.reply_text(f"❌ Error fetching balance: {exc}")

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if not self.trading_bot:
            await update.message.reply_text("❌ Trading bot not initialised.")
            return
        stats = self.trading_bot.db.get_stats()
        msg = (
            f"<b>📊 Trading Stats</b>\n"
            f"Total trades: {stats['total_trades']}\n"
            f"Wins: {stats['wins']}\n"
            f"Losses: {stats['losses']}\n"
            f"Win rate: {stats['win_rate']}%\n"
            f"Total P&amp;L: <b>${stats['total_pnl']:.4f}</b>\n"
        )
        await update.message.reply_text(msg)

    async def _cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorised(update):
            return
        if not self.trading_bot:
            await update.message.reply_text("❌ Trading bot not initialised.")
            return
        risk = self.trading_bot.risk_manager.status()
        msg = (
            f"<b>🛡️ Risk Parameters</b>\n"
            f"Max risk per trade: {risk['max_risk_per_trade_pct']}%\n"
            f"Daily loss limit: {risk['daily_loss_limit_pct']}%\n"
            f"Max open positions: {risk['max_open_positions']}\n"
            f"Day start balance: ${risk['day_start_balance']:.2f}\n"
        )
        await update.message.reply_text(msg)

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = (
            "<b>Available Commands</b>\n"
            "/start – Start trading bot\n"
            "/stop – Stop trading bot\n"
            "/status – Bot status &amp; positions\n"
            "/balance – Current USDC balance\n"
            "/stats – P&amp;L &amp; performance stats\n"
            "/risk – Risk parameter summary\n"
            "/help – This message\n"
        )
        await update.message.reply_text(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_authorised(self, update: Update) -> bool:
        """Only allow messages from the configured chat ID."""
        if not self.chat_id:
            return True
        if str(update.effective_chat.id) == str(self.chat_id):
            return True
        logger.warning("Unauthorised Telegram message from chat %s", update.effective_chat.id)
        return False
