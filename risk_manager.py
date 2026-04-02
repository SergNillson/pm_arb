"""Risk management module."""

import logging
from typing import Set, Tuple

from utils.database import Database

logger = logging.getLogger("polymarket_bot")


class RiskManager:
    """
    Enforces trading risk limits.

    Checks performed before every trade:
    - Maximum number of simultaneous open positions.
    - Daily loss limit (as a percentage of starting balance).
    - Per-trade risk cap.
    """

    def __init__(
        self,
        max_open_positions: int = 5,
        daily_loss_limit_pct: float = 2.0,
        max_risk_per_trade_pct: float = 0.5,
        database: Database = None,
    ):
        self.max_open_positions = max_open_positions
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.db = database

        # In-memory set of currently open position token IDs
        self._open_positions: Set[str] = set()
        # Balance at start of the day (set on first call)
        self._day_start_balance: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def can_open_position(self, current_balance: float) -> Tuple[bool, str]:
        """
        Decide whether a new position can be opened.

        Args:
            current_balance: Current account balance in USDC.

        Returns:
            (True, "") if the trade is allowed, (False, reason) otherwise.
        """
        # Initialise day-start balance on first use
        if self._day_start_balance == 0 and current_balance > 0:
            self._day_start_balance = current_balance

        # Check maximum open positions
        if len(self._open_positions) >= self.max_open_positions:
            return False, f"Max open positions reached ({self.max_open_positions})"

        # Check daily loss limit
        if self._day_start_balance > 0:
            daily_loss_pct = (
                (self._day_start_balance - current_balance) / self._day_start_balance * 100
            )
            if daily_loss_pct >= self.daily_loss_limit_pct:
                return (
                    False,
                    f"Daily loss limit reached ({daily_loss_pct:.2f}% >= {self.daily_loss_limit_pct}%)",
                )

        # Check database-based daily P&L if available
        if self.db and self._day_start_balance > 0:
            daily_pnl = self.db.get_daily_pnl()
            if daily_pnl < 0:
                daily_loss_pct = abs(daily_pnl) / self._day_start_balance * 100
                if daily_loss_pct >= self.daily_loss_limit_pct:
                    return (
                        False,
                        f"Daily loss limit reached via DB (${daily_pnl:.2f})",
                    )

        return True, ""

    def register_open_position(self, token_id: str) -> None:
        """Record a newly opened position."""
        self._open_positions.add(token_id)
        logger.debug("Position opened: %s (total open: %d)", token_id[:12], len(self._open_positions))

    def close_position(self, token_id: str) -> None:
        """Remove a closed position from the registry."""
        self._open_positions.discard(token_id)
        logger.debug("Position closed: %s (total open: %d)", token_id[:12], len(self._open_positions))

    def reset_day(self, current_balance: float) -> None:
        """Reset daily tracking (call at the start of each trading day)."""
        self._day_start_balance = current_balance
        logger.info("Risk manager daily reset. Start balance: $%.2f", current_balance)

    @property
    def open_position_count(self) -> int:
        return len(self._open_positions)

    def status(self) -> dict:
        """Return a dictionary summary of current risk state."""
        return {
            "open_positions": self.open_position_count,
            "max_open_positions": self.max_open_positions,
            "day_start_balance": self._day_start_balance,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
        }
