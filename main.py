# main.py
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import User, Wallet
from auth import verify_telegram_init_data  # جديد
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mrwiat Backend")

origins = [
    "https://mrwiat.com",
    "https://www.mrwiat.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# نموذج البيانات القادمة من WebApp
class TelegramInitData(BaseModel):
    init_data: str


def get_or_create_user_from_telegram(user_data: dict, db: Session) -> User:
    telegram_id = user_data["id"]
    first_name = user_data.get("first_name")
    username = user_data.get("username")

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(
            telegram_id=telegram_id,
            first_name=first_name,
            username=username,
        )
        db.add(user)
        db.flush()

        wallet = Wallet(user_id=user.id, balance_cents=0)
        db.add(wallet)
        db.commit()
        db.refresh(user)

    return user


@app.post("/wallet/webapp")
def wallet_from_webapp(
    payload: TelegramInitData,
    db: Session = Depends(get_db),
):
    user_data = verify_telegram_init_data(payload.init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    user = get_or_create_user_from_telegram(user_data, db)
    wallet = user.wallet

    return {
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "username": user.username,
        "balance_cents": wallet.balance_cents,
        "balance": wallet.balance_cents / 100,
        "currency": wallet.currency,
    }


# القديم فقط للاختبار المحلي لو حبيت تحتفظ به
def get_fake_user(db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == 123456789).first()
    if not user:
        user = User(telegram_id=123456789, first_name="Test", username="tester")
        db.add(user)
        db.flush()
        wallet = Wallet(user_id=user.id, balance_cents=0)
        db.add(wallet)
        db.commit()
        db.refresh(user)
    return user


@app.get("/wallet/me")
def wallet_me(db: Session = Depends(get_db), user: User = Depends(get_fake_user)):
    wallet = user.wallet
    return {
        "telegram_id": user.telegram_id,
        "balance_cents": wallet.balance_cents,
        "balance": wallet.balance_cents / 100,
        "currency": wallet.currency,
    }
