import random
import string
import sys
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal
from models import RedeemCode


def generate_random_code(length=10):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_codes(count, points):
    db: Session = SessionLocal()
    codes_list = []

    for _ in range(count):
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
            redeemed_at=None
        )

        db.add(new_code)
        db.commit()

        codes_list.append(code)

    db.close()
    return codes_list


def save_to_file(points, codes):
    file_name = f"codes_{points}.txt"
    with open(file_name, "w") as f:
        for c in codes:
            f.write(f"{c}\n")
    print(f"📁 Saved {len(codes)} codes to {file_name}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_codes.py <count> <points>")
        sys.exit(1)

    count = int(sys.argv[1])
    points = int(sys.argv[2])

    codes = generate_codes(count, points)

    print("\n⚡ Generated Codes:")
    for c in codes:
        print(f"{c}  ->  {points} points")

    save_to_file(points, codes)

    print("\n✨ Done! Codes saved and inserted into database.")
