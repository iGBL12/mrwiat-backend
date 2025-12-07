# manage_wallet.py
import sys
from sqlalchemy.orm import Session

from database import SessionLocal
from models import User, Wallet


def get_db() -> Session:
    return SessionLocal()


def show_wallet(telegram_id: int):
    db = get_db()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            print(f"❌ لا يوجد مستخدم بهذا telegram_id: {telegram_id}")
            return

        wallet = user.wallet
        if not wallet:
            print(f"❌ لا توجد محفظة لهذا المستخدم (id={user.id})")
            return

        print("===== معلومات المستخدم =====")
        print(f"DB id        : {user.id}")
        print(f"Telegram ID  : {user.telegram_id}")
        print(f"Name         : {user.first_name}")
        print(f"Username     : @{user.username}" if user.username else "Username : -")
        print("===== المحفظة =====")
        print(f"Balance raw  : {wallet.balance_cents} (كنقاط/سِنْت)")
        print(f"Balance view : {wallet.balance_cents / 100:.2f} {wallet.currency}")
    finally:
        db.close()


def add_points(telegram_id: int, delta_points: int):
    """
    يزيد أو ينقص نقاط المستخدم.
    delta_points ممكن تكون موجبة (إضافة) أو سالبة (خصم).
    """
    db = get_db()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user or not user.wallet:
            print("❌ لم أجد المستخدم أو محفظته.")
            return

        wallet = user.wallet
        old_balance = wallet.balance_cents
        new_balance = max(0, old_balance + delta_points)
        wallet.balance_cents = new_balance
        db.commit()

        print("✅ تم تحديث الرصيد بنجاح.")
        print(f"من: {old_balance} -> إلى: {new_balance}")
    finally:
        db.close()


def set_points(telegram_id: int, new_points: int):
    """
    يضبط رصيد المستخدم لقيمة معيّنة مباشرة.
    """
    db = get_db()
    try:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user or not user.wallet:
            print("❌ لم أجد المستخدم أو محفظته.")
            return

        wallet = user.wallet
        old_balance = wallet.balance_cents
        wallet.balance_cents = max(0, new_points)
        db.commit()

        print("✅ تم ضبط الرصيد بنجاح.")
        print(f"من: {old_balance} -> إلى: {wallet.balance_cents}")
    finally:
        db.close()


def usage():
    print(
        """
استخدام السكربت:

1) عرض رصيد مستخدم:
   python manage_wallet.py show <telegram_id>

2) إضافة / خصم نقاط:
   python manage_wallet.py add <telegram_id> <delta>

   أمثلة:
     إضافة 500 نقطة:
       python manage_wallet.py add 123456789 500

     خصم 200 نقطة:
       python manage_wallet.py add 123456789 -200

3) تعيين رصيد ثابت:
   python manage_wallet.py set <telegram_id> <new_balance>

   مثال:
     جعل رصيد المستخدم 0:
       python manage_wallet.py set 123456789 0
"""
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    command = sys.argv[1]
    telegram_id = int(sys.argv[2])

    if command == "show":
        show_wallet(telegram_id)
    elif command == "add":
        if len(sys.argv) < 4:
            print("❗ تحتاج تمرير قيمة للإضافة/الخصم.")
            usage()
            sys.exit(1)
        delta = int(sys.argv[3])
        add_points(telegram_id, delta)
    elif command == "set":
        if len(sys.argv) < 4:
            print("❗ تحتاج تمرير الرصيد الجديد.")
            usage()
            sys.exit(1)
        new_points = int(sys.argv[3])
        set_points(telegram_id, new_points)
    else:
        print(f"❌ أمر غير معروف: {command}")
        usage()
