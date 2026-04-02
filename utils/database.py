"""SQLite database module for storing trade history and performance metrics."""

import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session

DB_URL = "sqlite:///trades.db"


class Base(DeclarativeBase):
    pass


class Trade(Base):
    """Represents a single executed trade."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    market_id = Column(String, nullable=False)
    asset = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # YES / NO
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    size = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True)
    strategy = Column(String, nullable=False)
    status = Column(String, default="open")  # open / closed / cancelled
    paper = Column(Integer, default=1)  # 1 = paper, 0 = live


class Database:
    """Simple database wrapper around SQLAlchemy."""

    def __init__(self, url: str = DB_URL):
        self.engine = create_engine(url, echo=False)
        Base.metadata.create_all(self.engine)

    def add_trade(self, trade_data: dict) -> Trade:
        """Insert a new trade record and return it."""
        with Session(self.engine) as session:
            trade = Trade(**trade_data)
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade

    def close_trade(self, trade_id: int, exit_price: float, pnl: float) -> None:
        """Mark a trade as closed with the given exit price and P&L."""
        with Session(self.engine) as session:
            trade = session.get(Trade, trade_id)
            if trade:
                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.status = "closed"
                session.commit()

    def get_open_trades(self) -> list:
        """Return all currently open trades."""
        with Session(self.engine) as session:
            return session.query(Trade).filter(Trade.status == "open").all()

    def get_daily_pnl(self) -> float:
        """Return total P&L for trades closed today."""
        today = datetime.datetime.utcnow().date()
        with Session(self.engine) as session:
            result = session.execute(
                text(
                    "SELECT COALESCE(SUM(pnl), 0) FROM trades "
                    "WHERE status='closed' AND DATE(timestamp)=:today"
                ),
                {"today": str(today)},
            ).scalar()
            return float(result or 0)

    def get_stats(self) -> dict:
        """Return overall trading statistics."""
        with Session(self.engine) as session:
            total = session.query(Trade).filter(Trade.status == "closed").count()
            wins = (
                session.query(Trade)
                .filter(Trade.status == "closed", Trade.pnl > 0)
                .count()
            )
            total_pnl = session.execute(
                text("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='closed'")
            ).scalar()
            return {
                "total_trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": round((wins / total) * 100, 2) if total else 0,
                "total_pnl": round(float(total_pnl or 0), 4),
            }
