# auth.py
import hashlib
import hmac
from urllib.parse import parse_qsl
from typing import Optional, Dict
import os

from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # سنضعه في .env

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")


def verify_telegram_init_data(init_data: str) -> Optional[Dict]:
    """
    Verify Telegram WebApp initData string.
    Returns user dict if valid, else None.
    """
    if not init_data:
        return None

    # Parse key=value&key2=value2 ...
    data = dict(parse_qsl(init_data, strict_parsing=True))

    if "hash" not in data:
        return None

    hash_received = data.pop("hash")

    # Build data_check_string
    data_check_arr = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(data_check_arr)

    # Secret key
    secret_key = hashlib.sha256(f"WebAppData{BOT_TOKEN}".encode()).digest()

    # Calculate HMAC-SHA256
    hmac_calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if hmac_calculated != hash_received:
        return None

    # If valid, extract user JSON
    import json
    user_json = data.get("user")
    if not user_json:
        return None

    user = json.loads(user_json)
    return user
