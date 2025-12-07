# generate_codes.py
import random
import string

from database import SessionLocal
from models import RedeemCode

# ---------- إعدادات توليد الأكواد ----------

# طول الكود، مثلاً: ABCD9F7K
CODE_LENGTH = 10

# عدد النقاط لكل كود (عدّلها كما تريد)
POINTS_PER_CODE = 100

# كم كود تريد توليده في كل تشغيل للسكريبت
NUM_CODES = 20


def generate_random_code(length: int = CODE_LENGTH) -> str:
    """
    توليد كود عشوائي بأحرف كبيرة + أرقام،
    مع تجنّب الأحرف المربكة مثل O/0 و I/1.
    """
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.replace("O", "").replace("0", "")
    alphabet = alphabet.replace("I", "").replace("1", "")

    return "".join(random.choice(alphabet) for _ in range(length))


def generate_codes():
    db = SessionLocal()
    try:
        created_codes = []

        for _ in range(NUM_CODES):
            # توليد كود فريد (إذا طلع مكرر نعيد التوليد)
            while True:
                code_str = generate_random_code()
                exists = db.query(RedeemCode).filter_by(code=code_str).first()
                if not exists:
                    break

            new_code = RedeemCode(
                code=code_str,
                points=POINTS_PER_CODE,
                # created_at سيأخذ القيمة الافتراضية من الموديل/قاعدة البيانات
            )
            db.add(new_code)
            created_codes.append(new_code)

        db.commit()

        print("✅ تم إنشاء الأكواد التالية:\n")
        # نضمن أن IDs محدثة بعد commit
        for c in created_codes:
            print(f"{c.code}    ->   {c.points} نقطة")

        print("\n💡 انسخ هذه الأكواد وخزنها في مكان آمن (مثلاً ملف نصي خاص).")

    finally:
        db.close()


if __name__ == "__main__":
    generate_codes()
