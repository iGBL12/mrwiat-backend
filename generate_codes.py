# generate_codes.py
import random
import string

from database import SessionLocal
from models import RedeemCode

CODE_LENGTH = 10
POINTS_PER_CODE = 100
NUM_CODES = 20


def generate_random_code(length: int = CODE_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.replace("O", "").replace("0", "")
    alphabet = alphabet.replace("I", "").replace("1", "")
    return "".join(random.choice(alphabet) for _ in range(length))


def generate_codes():
    db = SessionLocal()
    try:
        created_codes = []

        for _ in range(NUM_CODES):
            while True:
                code_str = generate_random_code()
                exists = db.query(RedeemCode).filter_by(code=code_str).first()
                if not exists:
                    break

            new_code = RedeemCode(
                code=code_str,
                points=POINTS_PER_CODE,
            )

            db.add(new_code)
            db.commit()       # commit needed to generate ID
            db.refresh(new_code)

            created_codes.append(new_code)

        print("✅ Generated Codes:\n")
        for c in created_codes:
            print(f"{c.code}  ->  {c.points} points")

        print("\n💡 Save these codes somewhere safe.")

    finally:
        db.close()


if __name__ == "__main__":
    generate_codes()
