# models.py
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    first_name = Column(String(255))
    username = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    wallet = relationship("Wallet", uselist=False, back_populates="user")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    balance_cents = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wallet")
