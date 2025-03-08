# backend/models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Wallet(Base):
    """PostgreSQL model for wallets."""
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, unique=True, index=True, nullable=False)
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String, default="low")
    created_at = Column(DateTime, default=func.now())

class Transaction(Base):
    """PostgreSQL model for transactions."""
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String, unique=True, index=True, nullable=False)
    wallet_address = Column(String, ForeignKey("wallets.address"), nullable=False)
    amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    chain = Column(String, nullable=False)

if __name__ == "__main__":
    from sqlalchemy import create_engine
    engine = create_engine("postgresql://user:password@localhost:5432/crypto_db")
    Base.metadata.create_all(engine)