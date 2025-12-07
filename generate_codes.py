# generate_codes.py
import sys
import random
import string

from database import SessionLocal
from models import RedeemCode


def generate_one_code(length: int = 10) -> str:
    """توليد كود عشوائي من حروف كبيرة + أرقام."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


def generate_codes(count: int, points_per_code: int):
    """
    يولّد count كود، كل واحد بقيمة points_per_code نقطة،
    ويحفظها في قاعدة البيانات.
    """
    db = SessionLocal()
    created = []

    try:
        for _ in range(count):
            # تأكد أن الكود غير مكرر في الجدول
            while True:
                code = generate_one_code(10)
                exists = db.query(RedeemCode).filter_by(code=code).first()
                if not exists:
                    break

            obj = RedeemCode(
                code=code,
                points=points_per_code,   # 👈 هنا أهم شي: نستخدم عدد النقاط اللي مررته
            )
            db.add(obj)
            created.append(obj)

        db.commit()
        return created

    finally:
        db.close()


if __name__ == "__main__":
    # قراءة عدد الأكواد من argv أو افتراضي 20
    try:
        count = int(sys.argv[1]) if len(sys.argv) >= 2 else 20
    except ValueError:
        print("❌ أول باراميتر لازم يكون عدد الأكواد (int). مثال: python generate_codes.py 500 100")
        sys.exit(1)

    # قراءة عدد النقاط لكل كود من argv أو افتراضي 100
    try:
        points_per_code = int(sys.argv[2]) if len(sys.argv) >= 3 else 100
    except ValueError:
        print("❌ ثاني باراميتر لازم يكون عدد النقاط لكل كود (int). مثال: python generate_codes.py 500 100")
        sys.exit(1)

    codes = generate_codes(count, points_per_code)

    print("✅ Generated Codes:\n")

    # نطبع فقط أول 50 كود عشان لا يصير التيرمنال مجنون
    max_show = min(50, len(codes))
    for c in codes[:max_show]:
        print(f"{c.code:<12} -> {c.points:>4} points")

    if len(codes) > max_show:
        remaining = len(codes) - max_show
        print(f"\n… وتم إنشاء {remaining} كود إضافي (غير معروضة هنا).")

    print("\n💾 جميع الأكواد تم حفظها في قاعدة البيانات.")
