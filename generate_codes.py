import sys
import string
import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from database import SessionLocal
from models import RedeemCode


CODE_LENGTH = 10  # طول الكود، غيره لو حاب


def generate_random_code(length: int = CODE_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_codes_for_points(db: Session, count: int, points: int) -> list[str]:
    """
    يولّد عدد معيّن من الأكواد لنقاط معيّنة، ويحفظها في قاعدة البيانات.
    يرجّع قائمة الأكواد (strings) اللي انحفظت.
    """
    codes_list: list[str] = []

    for _ in range(count):
        # نضمن أن الكود ما يتكرر
        while True:
            code = generate_random_code()
            exists = db.query(RedeemCode).filter_by(code=code).first()
            if not exists:
                break

        new_code = RedeemCode(
            code=code,
            points=points,
            is_used=False,
            is_redeemed=False,
        )
        db.add(new_code)
        codes_list.append(code)

    db.commit()
    return codes_list


def write_codes_to_file(codes: list[str], points: int) -> str:
    """
    يكتب الأكواد في ملف نصّي مستقل لكل فئة نقاط.
    مثال اسم الملف: redeem_codes_50_20251207_204600.txt
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"redeem_codes_{points}_{timestamp}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Redeem codes for {points} points\n")
        f.write("=" * 40 + "\n\n")
        for c in codes:
            f.write(c + "\n")

    return filename


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python generate_codes.py <count_per_category> <points1> [<points2> ...]\n\n"
            "مثال:\n"
            "  python generate_codes.py 500 50 100 200\n"
            "سيولّد 500 كود من 50 نقطة، و500 من 100 نقطة، و500 من 200 نقطة."
        )
        sys.exit(1)

    try:
        count = int(sys.argv[1])
    except ValueError:
        print("❌ <count_per_category> يجب أن يكون رقمًا صحيحًا.")
        sys.exit(1)

    points_values = []
    for raw in sys.argv[2:]:
        try:
            p = int(ra
