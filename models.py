# models.py
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    ForeignKey,
    Boolean,
)
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

    # علاقة واحد لواحد مع المحفظة
    wallet = relationship("Wallet", uselist=False, back_populates="user")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    balance_cents = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wallet")


class RedeemCode(Base):
    __tablename__ = "redeem_codes"

    id = Column(Integer, primary_key=True, index=True)

    # الكود نفسه
    code = Column(String(32), unique=True, index=True, nullable=False)

    # عدد النقاط التي يعطيها الكود
    points = Column(Integer, nullable=False, default=0)

    # هل تم استخدام الكود داخل النظام (لمنع استخدامه أكثر من مرة)
    is_used = Column(Boolean, nullable=False, default=False)

    # هل تم استرداد الكود كنقاط في المحفظة
    is_redeemed = Column(Boolean, nullable=False, default=False)

    # رقم المستخدم الذي استخدم الكود (من جدول users)
    redeemed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    redeemed_at = Column(DateTime, nullable=True)

    # علاقة اختيارية مع المستخدم الذي استخدم الكود
    redeemed_by_user = relationship("User")
