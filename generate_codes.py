# generate_codes.py
import string
import random
from database import SessionLocal
from models import TopupCode

# عدد الأكواد التي تريد توليدها لكل باقة
GENERATE_COUNT = {
    50: 100,     # مثال: 10 أكواد فئة 50 نقطة
    100: 100,    # مثال: 10 أكواد فئة 100 نقطة
    500: 100,     # مثال: 5 أكواد فئة 500 نقطة
}

# توليد كود عشوائي
def generate_single_code(points: int) -> str:
    letters = string.ascii_uppercase + string.digits
    random_part = "".join(random.choices(letters, k=8))
    return f"MRW-{points}-{random_part}"

# التحقق أن الكود غير مكرر
def generate_unique_code(db, points: int) -> str:
    while True:
        code = generate_single_code(points)
        exists = db.query(TopupCode).filter(TopupCode.code == code).first()
        if not exists:
            return code

def main():
    db = SessionLocal()

    print("=== START GENERATING CODES ===")

    all_created = []

    for points, count in GENERATE_COUNT.items():
        created_for_points = []

        for _ in range(count):
            code = generate_unique_code(db, points)
            new_code = TopupCode(code=code, points=points, used=False)
            db.add(new_code)
            created_for_points.append(code)

        db.commit()
        all_created.append((points, created_for_points))

    print("\n=== GENERATED CODES ===")
    for points, codes in all_created:
        print(f"\n[{points} POINTS]")
        for c in codes:
            print(c)

    print("\n=== END ===")
    print("تم توليد الأكواد وتخزينها في قاعدة البيانات بنجاح ✔️")

    db.close()

if __name__ == "__main__":
    main()
