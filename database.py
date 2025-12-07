# database.py
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# -------------------------------------------------------------------
# قراءة رابط قاعدة البيانات من متغير البيئة DATABASE_URL
# Render يعطيك رابط مثل:
# postgres://USER:PASSWORD@HOST:PORT/DBNAME
# SQLAlchemy تفضّل الصيغة:
# postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DBNAME
# لذلك نعدّل البادئة إن لزم الأمر.
# -------------------------------------------------------------------

raw_db_url = os.environ.get("DATABASE_URL")

if not raw_db_url:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "اضبط متغير البيئة DATABASE_URL برابط PostgreSQL من لوحة Render."
    )

# تصحيح البادئة من postgres:// إلى postgresql+psycopg2:// إن لزم
if raw_db_url.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = raw_db_url.replace(
        "postgres://",
        "postgresql+psycopg2://",
        1,
    )
else:
    SQLALCHEMY_DATABASE_URL = raw_db_url

# -------------------------------------------------------------------
# إنشاء المحرك (Engine) و SessionLocal و Base
# -------------------------------------------------------------------

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # يتحقق من الاتصال قبل كل استخدام لتفادي الاتصالات الميتة
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """
    دالة تُستخدم في المسارات (FastAPI مثلاً) للحصول على Session
    مثال الاستخدام:

        def endpoint(depends: Depends(get_db)):
            db = depends
            ...

    أو في سكربت عادي:

        db = SessionLocal()
        try:
            ...
        finally:
            db.close()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
