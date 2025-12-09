import os
import random
import string
import sys
from datetime import datetime

from sqlalchemy.orm import Session

from database import SessionLocal
from models import RedeemCode


def generate_random_code(length=10):
    """توليد كود عشوائي من حروف كبيرة وأرقام بطول محدد."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_codes(count: int, points: int):
    """
    توليد عدد من الأكواد وتخزينها داخل قاعدة البيانات.
    الكود المخزن في DB هو نفس الذي سيُعطى للمستخدم (بدون أي بادئة).
    """
    db: Session = SessionLocal()
    codes_list = []

    try:
        for _ in range(count):
            # تأكد أن الكود غير مكرر
            while True:
                code = generate_random_code(10)
                exists = db.query(RedeemCode).filter_by(code=code).first()
                if not exists:
                    break

            new_code = RedeemCode(
                code=code,
                points=points,
                is_redeemed=False,
                redeemed_by_user_id=None,
                redeemed_at=None,
            )
            db.add(new_code)
            db.commit()

            codes_list.append(code)
    finally:
        db.close()

    return codes_list


def get_output_dir() -> str:
    """تحديد مجلد الحفظ باستخدام /var/data إذا موجود (ديسك Render)."""
    env_dir = os.environ.get("CODES_OUTPUT_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    if os.path.isdir("/var/data"):
        return "/var/data"

    return "."


def save_to_file(points: int, codes):
    """حفظ الأكواد في ملف TXT بدون أي بادئة."""
    out_dir = get_output_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = os.path.join(out_dir, f"codes_{points}_{timestamp}.txt")

    with open(file_name, "w", encoding="utf-8") as f:
        for c in codes:
            f.write(c + "\n")

    print(f"📁 Saved {len(codes)} codes to: {file_name}")
    if codes:
        print(f"🔑 Example code: {codes[0]}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_codes.py <count> <points>")
        print("Example: python generate_codes.py 50 100")
        sys.exit(1)

    count = int(sys.argv[1])
    points = int(sys.argv[2])

    codes = generate_codes(count, points)

    print("\n⚡ Generated Codes:")
    for c in codes:
        print(f"{c}  ->  {points} points")

    save_to_file(points, codes)

    print("\n✨ Done! Codes saved to database and file.")
