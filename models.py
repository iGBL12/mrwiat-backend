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

    wallet = relationship("Wallet", uselist=False, back_populates="user")
    # لو حبيت تعرف كل الأكواد اللي استخدمها هذا اليوزر مستقبلاً:
    # redeemed_codes = relationship("RedeemCode", back_populates="user")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    # تقدر تعتبرها رصيد نقاط مثلاً بدل سنتات
    balance_cents = Column(BigInteger, default=0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wallet")


class RedeemCode(Base):
    __tablename__ = "redeem_codes"

    id = Column(Integer, primary_key=True, index=True)
    # الكود نفسه اللي بتبيعه في سلة
    code = Column(String(64), unique=True, index=True, nullable=False)
    # عدد النقاط اللي يعطيها هذا الكود (مثلاً 50 أو 100 أو 150 أو 200)
    points = Column(Integer, nullable=False)

    # هل تم استخدامه أم لا
    is_used = Column(Boolean, default=False, nullable=False)

    # من هو المستخدم اللي استخدمه (اختياري حالياً)
    used_by_telegram_id = Column(BigInteger, nullable=True)
    used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # لو أردت ربطه بـ User كـ relationship (اختياري الآن):
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # user = relationship("User", back_populates="redeemed_codes")
