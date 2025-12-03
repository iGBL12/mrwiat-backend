# auth.py
import json
from urllib.parse import parse_qsl


def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    نسخة مبسّطة: لا تتحقق من التوقيع (hash)، فقط تقرأ user من init_data.
    هذا مناسب للاختبار والتطوير. لاحقًا نعيد تفعيل التحقق الكامل.
    """
    if not init_data:
        return None

    # تحويل init_data من query string إلى dict
    data = dict(parse_qsl(init_data, keep_blank_values=True))

    user_json = data.get("user")
    if not user_json:
        return None

    try:
        user_data = json.loads(user_json)
    except json.JSONDecodeError:
        return None

    return user_data
