# auth.py
import os
import hmac
import hashlib
import json
from urllib.parse import parse_qsl

# نستخدم نفس المتغير الذي يستخدمه bot.py
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")


def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    التحقق من init_data حسب توثيق تيليجرام:
    https://core.telegram.org/bots/webapps#validating-data-received-via-mini-apps

    تعيد dict لمعلومات المستخدم (id, first_name, username) أو None لو فشل التحقق.
    """
    if not init_data:
        return None

    # 1) نحول init_data من query string إلى dict
    data = dict(parse_qsl(init_data, keep_blank_values=True))

    # 2) نأخذ الـ hash المُرسل ونزيله من البيانات
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    # 3) نكوّن data_check_string بترتيب المفاتيح أبجديًّا
    data_check_arr = [f"{k}={v}" for k, v in sorted(data.items())]
    data_check_string = "\n".join(data_check_arr)

    # 4) نحتسب HMAC باستخدام sha256(bot_token)
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calc_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    # 5) لو الـ hash غير مطابق → init data غير صحيحة
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    # 6) نفك JSON الخاص بالمستخدم ونرجعه على شكل dict
    user_json = data.get("user")
    if not user_json:
        return None

    try:
        user_data = json.loads(user_json)
    except json.JSONDecodeError:
        return None

    # الآن user_data يحتوي: id, first_name, username, ...
    return user_data
