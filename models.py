from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from db.session import Base  # ✅ FIXED

class ArbitrageAlert(Base):
    __tablename__ = "arbitrage_alert"
    id = Column(Integer, primary_key=True)
    asset1 = Column(String(20), nullable=False)
    asset2 = Column(String(20), nullable=False)
    exchange1 = Column(String(20), nullable=False)
    exchange2 = Column(String(20), nullable=False)
    price1 = Column(Float, nullable=False)
    price2 = Column(Float, nullable=False)
    spread_percentage = Column(Float, nullable=False)
    spread_amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class MonitoredSymbol(Base):
    __tablename__ = "monitored_symbol"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    exchange = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True)
    threshold_percentage = Column(Float, default=0.5)
    threshold_amount = Column(Float, default=10.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class MarketData(Base):
    __tablename__ = "market_data"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    exchange = Column(String(20), nullable=False)
    best_bid = Column(Float)
    best_ask = Column(Float)
    bid_size = Column(Float)
    ask_size = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class TelegramChat(Base):
    __tablename__ = "telegram_chat"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(50), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    arbitrage_enabled = Column(Boolean, default=False)
    market_view_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
