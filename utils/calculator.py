"""Calculator utilities for trading edge and position sizing."""

from typing import Optional


def calculate_edge(
    spot_price: float,
    polymarket_yes_price: float,
    direction: str,
) -> float:
    """
    Calculate the edge (advantage) between the spot price movement
    and the current Polymarket price for a binary Up/Down market.

    Args:
        spot_price: Current price from a spot exchange (normalised 0-1 probability).
        polymarket_yes_price: Current YES price on Polymarket (0-1).
        direction: "YES" or "NO".

    Returns:
        Edge as a percentage (positive = favourable).
    """
    if direction == "YES":
        edge = (spot_price - polymarket_yes_price) * 100
    else:
        edge = ((1 - spot_price) - (1 - polymarket_yes_price)) * 100
    return round(edge, 4)


def calculate_position_size(
    balance: float,
    max_risk_pct: float,
    price: float,
    min_size: float = 1.0,
) -> float:
    """
    Calculate the position size based on balance and max risk percentage.

    Args:
        balance: Current account balance in USD.
        max_risk_pct: Maximum risk per trade as a percentage (e.g. 0.5).
        price: Current price of the outcome share (0-1).
        min_size: Minimum position size in USD.

    Returns:
        Position size in USD.
    """
    risk_amount = balance * (max_risk_pct / 100)
    size = risk_amount / price if price > 0 else 0.0
    return max(round(size, 2), min_size)


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    size: float,
    direction: str = "YES",
) -> float:
    """
    Calculate profit/loss for a closed position.

    Args:
        entry_price: Price at which the position was opened.
        exit_price: Price at which the position was closed.
        size: Position size in shares.
        direction: "YES" or "NO".

    Returns:
        P&L in USD.
    """
    if direction == "YES":
        return round((exit_price - entry_price) * size, 4)
    return round((entry_price - exit_price) * size, 4)


def win_rate(wins: int, total: int) -> Optional[float]:
    """Return win rate as a percentage, or None if no trades."""
    if total == 0:
        return None
    return round((wins / total) * 100, 2)
