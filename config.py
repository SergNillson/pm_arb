"""Configuration module: loads settings from .env file."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Central configuration loaded from environment variables."""

    # Polymarket
    POLYMARKET_API_KEY: str = os.getenv("POLYMARKET_API_KEY", "")
    POLYMARKET_PRIVATE_KEY: str = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    POLYMARKET_WALLET_ADDRESS: str = os.getenv("POLYMARKET_WALLET_ADDRESS", "")

    # Exchange APIs
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET_KEY: str = os.getenv("BINANCE_SECRET_KEY", "")
    BYBIT_API_KEY: str = os.getenv("BYBIT_API_KEY", "")
    BYBIT_SECRET_KEY: str = os.getenv("BYBIT_SECRET_KEY", "")
    COINBASE_API_KEY: str = os.getenv("COINBASE_API_KEY", "")
    COINBASE_SECRET_KEY: str = os.getenv("COINBASE_SECRET_KEY", "")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Trading mode
    PAPER_TRADING: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"

    # Risk parameters
    MAX_RISK_PER_TRADE: float = float(os.getenv("MAX_RISK_PER_TRADE", "0.5"))
    DAILY_LOSS_LIMIT: float = float(os.getenv("DAILY_LOSS_LIMIT", "2.0"))
    MIN_EDGE_PERCENTAGE: float = float(os.getenv("MIN_EDGE_PERCENTAGE", "10.0"))
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))

    # Strategies
    ENABLE_LATENCY_ARBITRAGE: bool = os.getenv("ENABLE_LATENCY_ARBITRAGE", "true").lower() == "true"
    ENABLE_MARKET_MAKING: bool = os.getenv("ENABLE_MARKET_MAKING", "false").lower() == "true"
    ENABLE_COPY_TRADING: bool = os.getenv("ENABLE_COPY_TRADING", "false").lower() == "true"

    # Time frames
    TRADE_5MIN: bool = os.getenv("TRADE_5MIN", "true").lower() == "true"
    TRADE_15MIN: bool = os.getenv("TRADE_15MIN", "true").lower() == "true"
    TRADE_1HOUR: bool = os.getenv("TRADE_1HOUR", "true").lower() == "true"

    # Assets
    ASSETS: list = [a.strip() for a in os.getenv("ASSETS", "BTC,ETH,SOL,XRP").split(",")]

    def validate(self) -> bool:
        """Validate that required configuration values are present."""
        if not self.PAPER_TRADING:
            required = [
                ("POLYMARKET_API_KEY", self.POLYMARKET_API_KEY),
                ("POLYMARKET_PRIVATE_KEY", self.POLYMARKET_PRIVATE_KEY),
                ("POLYMARKET_WALLET_ADDRESS", self.POLYMARKET_WALLET_ADDRESS),
            ]
            for name, value in required:
                if not value:
                    raise ValueError(f"Missing required config: {name}")
        return True


config = Config()
