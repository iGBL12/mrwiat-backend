# generate_codes.py

import random
import string
from database import SessionLocal
from models import RedeemCode

# عدد الأكواد لكل فئة
GENERATE_COUNT = {
    50: 10,
    100: 10,
    500: 5,
}

def generate_random_code(length=10):
    """Generate a random uppercase alphanumeric code."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_codes():
    db = SessionLocal()

    for points, qty in GENERATE_COUNT.items():
        for _ in range(qty):

            # توليد كود عشوائي
            code = generate_random_code(12)

            # التأكد أنه غير موجود مسبقاً
            exists = db.query(RedeemCode).filter_by(code=code).first()
            while exists:
                code = generate_random_code(12)
                exists = db.query(RedeemCode).filter_by(code=code).first()

            # إنشاء الكود
            new_code = RedeemCode(
                code=code,
                points=points,
                is_redeemed=False,
            )

            db.add(new_code)
            print(f"Generated code → {code}  ({points} points)")

    db.commit()
    db.close()
    print("\n✅ DONE — All codes added to PostgreSQL.")


if __name__ == "__main__":
    generate_codes()
