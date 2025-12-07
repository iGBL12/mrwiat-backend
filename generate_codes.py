# generate_codes.py
import sys
import random
import string

from database import SessionLocal
from models import RedeemCode


# -----------------------------
# توليد كود واحد
# -----------------------------
def generate_one_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits

    # إزالة أحرف تسبب لبس
    alphabet = alphabet.replace("O", "").replace("0", "")
    alphabet = alphabet.replace("I", "").replace("1", "")

    return "".join(random.choice(alphabet) for _ in range(length))


# -----------------------------
# توليد عدد من الأكواد
# -----------------------------
def generate_codes(count: int, points_per_code: int):
    db = SessionLocal()
    created_codes = []

    try:
        for _ in range(count):
            # ضمان عدم التكرار
            while True:
                code = generate_one_code()
                exists = db.query(RedeemCode).filter_by(code=code).first()
                if not exists:
                    break

            new_code = RedeemCode(
                code=code,
                points=points_per_code,
            )

            db.add(new_code)
            db.commit()
            db.refresh(new_code)

            created_codes.append(new_code)

        return created_codes

    finally:
        db.close()


# -----------------------------
# نقطة التشغيل الرئيسية
# -----------------------------
if __name__ == "__main__":
    # عدد الأكواد
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    # عدد النقاط لكل كود
    points = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    codes = generate_codes(count, points)

    print("✅ Generated Codes:\n")

    # 🔥 اطبع كل الأكواد بدون أي اختصار
    for c in codes:
        print(f"{c.code}    ->    {c.points} points")

    print(f"\n💾 تم توليد {len(codes)} كود وطباعة جميع الأكواد بالكامل.")
    print("📌 انسخ الأكواد الآن من التيرمنال وضعها في متجر سلة أو Excel.")
