# Polymarket Trading Bot 🤖

An automated trading bot for [Polymarket](https://polymarket.com) that implements multiple algorithmic trading strategies, including latency arbitrage, market making, and copy trading (scaffolded for future use).

> ⚠️ **Risk Warning**: Algorithmic trading involves significant financial risk. Always test in Paper Trading mode first. Past performance is no guarantee of future results. Use at your own risk.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Strategies](#strategies)
- [Telegram Commands](#telegram-commands)
- [Risk Management](#risk-management)
- [Paper Trading](#paper-trading)
- [FAQ & Troubleshooting](#faq--troubleshooting)
- [License](#license)

---

## Features

- ✅ **Latency Arbitrage** – detects price lag between centralised exchanges and Polymarket
- ✅ **Market Making** – places resting limit orders to earn the spread and rebates
- ✅ **Copy Trading** – mirrors trades from top wallets (basic scaffolding, extensible)
- ✅ **Multi-exchange price feeds** – Binance, Bybit, Coinbase via REST + WebSocket
- ✅ **Polymarket CLOB API** integration (market/limit orders, positions, balance)
- ✅ **Telegram bot** for real-time control and monitoring
- ✅ **Risk management** – per-trade limits, daily loss limit, max open positions
- ✅ **Paper trading mode** – simulate trades safely before going live
- ✅ **SQLite trade history** – P&L tracking, win rate, performance statistics
- ✅ **Rotating log files** – full debug logs, INFO on console
- ✅ **Async/await** throughout for maximum throughput and low latency
- ✅ **Graceful shutdown** on Ctrl+C / SIGTERM

---

## Architecture

```
pm_arb/
├── main.py                  # Entry point & orchestrator
├── config.py                # .env configuration loader
├── risk_manager.py          # Risk limits enforcement
├── telegram_bot.py          # Telegram control interface
├── strategies/
│   ├── latency_arbitrage.py # Spot-to-Polymarket arb strategy
│   ├── market_making.py     # CLOB limit-order market making
│   └── copy_trading.py      # Wallet copy trading
├── exchanges/
│   ├── polymarket.py        # Polymarket CLOB API client
│   ├── binance.py           # Binance REST + WebSocket
│   ├── bybit.py             # Bybit REST + WebSocket
│   └── coinbase.py          # Coinbase Advanced Trade
├── utils/
│   ├── logger.py            # Logging setup (file + console)
│   ├── calculator.py        # Edge, P&L, position sizing
│   └── database.py          # SQLAlchemy trade history DB
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Installation

### Prerequisites

- Python 3.10 or later
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/SergNillson/pm_arb.git
cd pm_arb

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the example environment file
cp .env.example .env

# 5. Edit .env and add your API keys
nano .env   # or use any text editor
```

---

## Configuration

All configuration is done via the `.env` file.  Never commit this file to version control.

| Variable | Description | Default |
|---|---|---|
| `POLYMARKET_API_KEY` | Polymarket CLOB API key | – |
| `POLYMARKET_PRIVATE_KEY` | Wallet private key (live trading only) | – |
| `POLYMARKET_WALLET_ADDRESS` | Your Polygon wallet address | – |
| `BINANCE_API_KEY` | Binance read-only API key | – |
| `BYBIT_API_KEY` | Bybit read-only API key | – |
| `COINBASE_API_KEY` | Coinbase Advanced Trade key | – |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather | – |
| `TELEGRAM_CHAT_ID` | Your Telegram chat/user ID | – |
| `PAPER_TRADING` | `true` = simulate, `false` = live | `true` |
| `MAX_RISK_PER_TRADE` | Max % of balance per trade | `0.5` |
| `DAILY_LOSS_LIMIT` | Max daily loss % before trading halts | `2.0` |
| `MIN_EDGE_PERCENTAGE` | Minimum detected edge to enter trade | `10.0` |
| `MAX_OPEN_POSITIONS` | Maximum simultaneous open positions | `5` |
| `ENABLE_LATENCY_ARBITRAGE` | Enable latency arb strategy | `true` |
| `ENABLE_MARKET_MAKING` | Enable market-making strategy | `false` |
| `ENABLE_COPY_TRADING` | Enable copy trading strategy | `false` |
| `TRADE_5MIN` | Include 5-minute markets | `true` |
| `TRADE_15MIN` | Include 15-minute markets | `true` |
| `TRADE_1HOUR` | Include 1-hour markets | `true` |
| `ASSETS` | Comma-separated list of assets | `BTC,ETH,SOL,XRP` |

---

## Running the Bot

```bash
# Paper trading (safe – default)
python main.py

# Live trading (requires real API credentials in .env with PAPER_TRADING=false)
python main.py
```

The bot will:
1. Validate configuration
2. Connect to exchange WebSocket feeds
3. Start all enabled strategies
4. Send a Telegram notification when ready
5. Run until you press Ctrl+C

---

## Strategies

### Latency Arbitrage

Monitors real-time spot prices from Binance, Bybit, and Coinbase.  When the spot price movement implies a high probability of a binary outcome that differs from the current Polymarket YES price by more than `MIN_EDGE_PERCENTAGE`, the bot enters a position.

**How it works:**
1. Receives tick-by-tick price updates via WebSocket from three exchanges.
2. Computes a directional probability based on recent price momentum using a sigmoid function applied to the percentage change.
3. Fetches the current Polymarket YES price from the CLOB order book.
4. If `theoretical_probability - polymarket_price > MIN_EDGE / 100`, places a market buy order on the appropriate outcome.

### Market Making

Places symmetric limit orders (BID and ASK) around the current mid price with a configurable spread.  Orders are refreshed whenever the mid price moves more than half the spread.

- Focuses on liquid short-term crypto Up/Down markets.
- Caps the portfolio at 20 simultaneously quoted markets.
- Position size is calculated from the current balance and `MAX_RISK_PER_TRADE`.

### Copy Trading

Polls the Polymarket data API for recent trades by a list of configured top wallets.  When a new trade is detected, it is mirrored with position sizing scaled to the bot's current risk parameters.

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Start the trading bot |
| `/stop` | Stop the trading bot |
| `/status` | Show running status and open positions |
| `/balance` | Show current USDC balance |
| `/stats` | Show P&L, win rate, and trade count |
| `/risk` | Show current risk parameters |
| `/help` | List all commands |

---

## Risk Management

The `RiskManager` enforces the following limits before every trade:

1. **Max open positions** – if the number of open positions equals `MAX_OPEN_POSITIONS`, no new trades are opened.
2. **Daily loss limit** – if the account balance has dropped by `DAILY_LOSS_LIMIT`% from the day's starting value, trading is halted until the next day.
3. **Per-trade size** – position size is automatically capped at `MAX_RISK_PER_TRADE`% of the current balance.

---

## Paper Trading

Paper trading mode (`PAPER_TRADING=true`) is enabled by default.  In this mode:
- All orders are logged but **not sent** to Polymarket.
- Balance and position tracking still work using simulated values.
- The database stores paper trades separately so they can be analysed.

Switch to live trading only after validating the strategy with at least several days of paper trading.

---

## FAQ & Troubleshooting

**Q: The bot starts but does not trade.**
- Check that `ENABLE_LATENCY_ARBITRAGE=true` in `.env`.
- Ensure price feeds are connecting (check `logs/bot.log`).
- The minimum edge threshold (`MIN_EDGE_PERCENTAGE`) may be too high.

**Q: I see "Risk block" messages.**
- The risk manager is preventing trades due to daily loss limit or max positions.
- Review `logs/bot.log` for the specific reason.

**Q: Telegram commands are not working.**
- Ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly.
- Start a conversation with the bot in Telegram first (`/start`).

**Q: How do I add more wallets to copy trade?**
- Modify the `watched_wallets` list in `strategies/copy_trading.py` or extend `config.py` to read them from `.env`.

**Q: The WebSocket keeps disconnecting.**
- This is normal; the bot will automatically reconnect after 5 seconds.

---

## License

This project is released under the [MIT License](LICENSE).

---

*Developed as an open-source reference implementation for Polymarket algorithmic trading.*

