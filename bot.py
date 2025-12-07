# bot.py
import os
import logging
import json
import time
from io import BytesIO
from textwrap import wrap
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    Filters,
    CallbackContext,
)

from openai import OpenAI
import PyPDF2
import requests
from pricing_config import get_pricing_text

# SQLAlchemy / DB
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, DateTime
from sqlalchemy.orm import Session

from database import Base, engine, SessionLocal

# =============== الإعدادات العامة ===============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

# مفاتيح Runway لإنتاج الفيديو
RUNWAY_API_KEY = os.environ.get("RUNWAY_API_KEY")
# نستخدم text_to_video حسب توثيق Runway
RUNWAY_API_URL = os.environ.get(
    "RUNWAY_API_URL",
    "https://api.dev.runwayml.com/v1/text_to_video",
)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06")
RUNWAY_MODEL = os.environ.get("RUNWAY_MODEL", "veo3.1")  # موديل افتراضي

# Endpoint لجلب تفاصيل المهمة من Runway
RUNWAY_TASKS_URL = os.environ.get(
    "RUNWAY_TASKS_URL",
    "https://api.dev.runwayml.com/v1/tasks",
)

# القروب / القناة التي سيتم النشر فيها عند الموافقة على القصة
COMMUNITY_CHAT_ID = os.environ.get("COMMUNITY_CHAT_ID")  # مثال: -1001234567890

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Story generation / review will fail.")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

# ======== نماذج قاعدة البيانات (SQLAlchemy ORM) =========

class UserWallet(Base):
    """
    جدول المحفظة لكل مستخدم تيليجرام.
    user_id = Telegram user id
    points  = رصيد النقاط
    """
    __tablename__ = "user_wallets"

    user_id = Column(BigInteger, primary_key=True, index=True)
    points = Column(Integer, nullable=False, default=0)


class TopupCode(Base):
    """
    جدول أكواد الشحن التي تُباع عبر سلة.
    code    = النص الذي يكتبه المستخدم في البوت
    points  = عدد النقاط التي يضيفها هذا الكود
    is_used = هل تم استخدامه سابقاً؟
    used_by = Telegram user id الذي استخدمه
    used_at = وقت الاستخدام
    """
    __tablename__ = "topup_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    points = Column(Integer, nullable=False)
    is_used = Column(Boolean, nullable=False, default=False)
    used_by = Column(BigInteger, nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)


# إنشاء الجداول لو لم تكن موجودة (بسيطة، مناسبة كبداية)
Base.metadata.create_all(bind=engine)

# ======== أسعار النقاط حسب الخدمات =========

IMAGE_COST_POINTS = 10        # من جدولك
STORY_COST_POINTS = 20        # قصة قصيرة

def get_video_cost_points(duration_seconds: int) -> int:
    if duration_seconds <= 10:
        return 40
    elif duration_seconds <= 15:
        return 55
    elif duration_seconds <= 20:
        return 70
    else:
        return 100  # للاحتياط لو زادت المدة مستقبلاً

# =============== ثوابت الحالات في المحادثة ===============

STATE_STORY_GENRE = 1       # اختيار نوع القصة
STATE_STORY_BRIEF = 2       # وصف فكرة القصة
STATE_PUBLISH_STORY = 3     # نص القصة أو PDF الذي يريد المستخدم نشره
STATE_VIDEO_IDEA = 4        # الفكرة الأولية للفيديو
STATE_VIDEO_CLARIFY = 5     # إجابات المستخدم على أسئلة التوضيح
STATE_IMAGE_PROMPT = 6      # وصف الصورة
STATE_VIDEO_DURATION = 7    # مدة الفيديو بالثواني
STATE_VIDEO_STATUS_ID = 8   # استعلام عن فيديو سابق برقم الطلب
STATE_REDEEM_CODE = 9       # إدخال كود شحن من سلة

# لوحة الأزرار الرئيسية
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["✍️ كتابة قصة بالذكاء الاصطناعي"],
        ["📤 نشر قصة من كتابتك"],
        ["🎬 إنتاج فيديو بالذكاء الاصطناعي", "🖼 إنشاء صورة بالذكاء الاصطناعي"],
        ["📥 استعلام عن فيديو سابق"],
        ["💰 الأسعار والنقاط", "💳 المحفظة / الشحن"],
        ["🎟 شحن برمز من سلة"],
    ],
    resize_keyboard=True,
)

# لوحة اختيار نوع القصة
GENRE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["غموض 🕵️‍♂️", "رعب 👻"],
        ["خيال علمي 🚀", "رومانسية 💕"],
        ["دراما 🎭", "مغامرة 🏝️"],
        ["نوع آخر"],
    ],
    resize_keyboard=True,
)

# =============== SYSTEM PROMPTS ===============

SYSTEM_PROMPT = """
أنت كاتب قصص عربي محترف تعمل لصالح منصة "مرويات".
مهمتك إنتاج قصص بجودة عالية، لغة ممتعة، وحبكة جذابة، مع أسلوب سرد خاص يتميّز بما يلي:

1. اللغة:
- اللغة عربية فصحى سهلة وبسيطة، مفهومة لجميع الفئات.
- تجنّب الكلمات المعقدة أو القديمة.
- اكتب بأسلوب أدبي مشوّق دون مبالغة.

2. أسلوب السرد:
- البداية تمهيد جذاب يدخل القارئ مباشرة في الجو العام.
- بناء الأحداث تدريجيًا لصنع التشويق.
- تقديم الشخصيات بعمق نفسي بسيط بدون إطالة.
- وصف الأماكن بشكل سينمائي مختصر (3–4 أسطر فقط).
- إدراج حوارات طبيعية تزيد من قوة القصة.

3. الحبكة:
- يجب أن تحتوي القصة على: بداية – عقدة – ذروة – حل.
- تجنب التكرار والحشو.
- النهاية يجب أن تكون مرضية، محكمة، وقابلة للتذكّر.

4. التنسيق:
- قسّم القصة إلى فقرات قصيرة لسهولة القراءة على تيليجرام.
- استخدم أسلوب يجذب القارئ ويجعله يكمل للآخر.
- لا تخرج عن مضمون فكرة المستخدم ولا عن نوع القصة المطلوب.

5. الطول:
- اجعل طول القصة بين 900 إلى 1300 كلمة تقريباً.
- إن كانت الفكرة بسيطة، أضف تفاصيل خفيفة لتعميق الأحداث.

6. المحظورات:
- تجنب أي محتوى مخالف للسياسات أو حساس أو سياسي أو عنيف بشكل مبالغ فيه.
- لا تذكر الدين أو الجنس أو الشذوذ أو المحتوى غير اللائق.

هدفك النهائي هو كتابة قصة ممتعة بجودة عالية تجعل القارئ يشعر بأنه يشاهد فيلمًا قصيرًا مكتوبًا بإتقان.
"""

REVIEW_PROMPT = """
أنت محرر رئيسي في منصة "مرويات" للقصص العربية.

سيتم إرسال نص قصة كاملة إليك (سواء مأخوذة من ملف PDF أو نص مباشرة من المستخدم).
مهمتك:

1. التأكد أن القصة:
   - مكتوبة باللغة العربية الفصحى السهلة.
   - خالية من المحتوى المخالف (سياسة، عنف مبالغ، عنصرية، محتوى جنسي، ألفاظ نابية...إلخ).
   - تحتوي على بداية وعقدة وذروة ونهاية.
   - لها بنية قصصية واضحة وشخصيات وأحداث مترابطة.
   - طولها مناسب للنشر (يفضل 1000 كلمة فأكثر).

2. أعد تقييم القصة وأخبرنا:
   - هل تصلح للنشر في قسم "قصص المجتمع" في مرويات؟
   - إن لم تكن صالحة، اذكر السبب الرئيسي باختصار.

3. أعد النتيجة في صيغة JSON فقط بدون أي نص إضافي، بالشكل التالي حرفياً:

{
  "approved": true أو false,
  "word_count": عدد الكلمات التقريبي كعدد صحيح,
  "title": "عنوان مقترح قصير للقصة",
  "reasons": "شرح مختصر لسبب القبول أو الرفض",
  "suggestions": "نصائح لتحسين القصة إن لزم الأمر"
}

لا تُرجع أي شيء خارج JSON، ولا تستخدم تعليقات أو نصوص أخرى.
"""

VIDEO_PROMPT_SYSTEM = """
أنت خبير في صناعة برومبت احترافي لمولد فيديو مثل Runway Gen-2.

مهمتك:
1. استلام وصف لفكرة فيديو من المستخدم (غالباً بالعربية).
2. تقييم وضوح الفكرة.
3. إذا كانت الفكرة غير كافية، اطلب تفاصيل إضافية عن:
   - الشخصيات (العمر، الشكل، الملابس)
   - المكان (مدينة، غرفة، طبيعة، ليل/نهار)
   - أسلوب التصوير (سينمائي، لقطة ثابتة، حركة كاميرا...)
   - المزاج (غامض، مرح، رعب، حزين...)
   - مدة الفيديو (مثلاً 5–10 ثوانٍ، 10–20 ثانية).
4. إذا كانت الفكرة كافية، أنشئ برومبت نهائي باللغة الإنجليزية، مفصل وواضح وجاهز للإرسال إلى Runway.

أعد النتيجة دائماً في صيغة JSON فقط بهذا الشكل:

إذا كانت الفكرة غير واضحة بما يكفي:
{
  "status": "need_more",
  "questions": [
    "اكتب هنا سؤالاً بالعربية لطلب تفاصيل أكثر...",
    "سؤال آخر لو أردت..."
  ]
}

إذا كانت الفكرة واضحة ومكتملة:
{
  "status": "ok",
  "final_prompt": "English detailed prompt for Runway...",
  "duration_seconds": 10,
  "aspect_ratio": "16:9"
}

لا تخرج عن هذا الشكل أبداً، ولا تضف أي نص خارجه.
"""

IMAGE_PROMPT_SYSTEM = """
أنت مهندس برومبت للصور (Image Prompt Engineer) تعمل مع نموذج صور متقدم.

مهمتك:
- استلام وصف صورة من المستخدم (غالباً بالعربية).
- تحويله إلى برومبت باللغة الإنجليزية، مفصل وواضح، يناسب نموذج صور مثل DALL·E / GPT-Image.
- أضف تفاصيل عن الإضاءة، الأسلوب الفني، زاوية الكاميرا إذا لزم.

أعد النتيجة كنص واحد فقط: البرومبت باللغة الإنجليزية بدون أي شرح إضافي.
"""

# =============== دوال المحفظة باستخدام قاعدة البيانات ===============

def get_user_id(update: Update) -> int:
    return update.effective_user.id


def get_user_balance(user_id: int) -> int:
    """
    جلب رصيد المستخدم من جدول user_wallets.
    إن لم يكن له صف، يتم إنشاؤه برصيد 0.
    """
    db: Session = SessionLocal()
    try:
        wallet = db.get(UserWallet, user_id)
        if wallet is None:
            wallet = UserWallet(user_id=user_id, points=0)
            db.add(wallet)
            db.commit()
            db.refresh(wallet)
        return wallet.points
    except Exception as e:
        logger.exception("get_user_balance error: %s", e)
        return 0
    finally:
        db.close()


def add_user_points(user_id: int, delta: int) -> int:
    """
    إضافة/خصم نقاط من المحفظة في قاعدة البيانات.
    ترجع الرصيد الجديد.
    """
    db: Session = SessionLocal()
    try:
        wallet = db.get(UserWallet, user_id)
        if wallet is None:
            wallet = UserWallet(user_id=user_id, points=0)
            db.add(wallet)
        wallet.points = max(0, (wallet.points or 0) + delta)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        return wallet.points
    except Exception as e:
        logger.exception("add_user_points error: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


def require_points(update: Update, needed_points: int) -> bool:
    """
    يتحقق هل لدى المستخدم رصيد كافٍ.
    لو لا، يرسل له رسالة أن يشحن المحفظة ويرجع False.
    """
    user_id = get_user_id(update)
    balance = get_user_balance(user_id)
    if balance < needed_points:
        short = needed_points - balance
        update.message.reply_text(
            f"❌ رصيدك الحالي: {balance} نقطة.\n"
            f"هذه الخدمة تحتاج: {needed_points} نقطة.\n"
            f"ينقصك: {short} نقطة.\n\n"
            "💳 اشترِ كود شحن من متجر *مرويات* في سلة ثم استخدم الأمر /redeem "
            "أو زر 🎟 شحن برمز من سلة لإضافة الرصيد.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return False
    return True


def require_and_deduct(update: Update, needed_points: int) -> bool:
    """
    يتحقق أن الرصيد كافٍ ثم يخصم النقاط من المحفظة (في DB).
    لو نجح يرجع True، لو لم يكن الرصيد كافياً يرجع False.
    """
    if not require_points(update, needed_points):
        return False
    user_id = get_user_id(update)
    new_balance = add_user_points(user_id, -needed_points)
    update.message.reply_text(
        f"✅ تم خصم {needed_points} نقطة من محفظتك.\n"
        f"🔢 رصيدك الحالي: {new_balance} نقطة.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return True


# =============== دوال أكواد الشحن من سلة ===============

def redeem_code_in_db(code: str, telegram_id: int):
    """
    يحاول تفعيل كود شحن من جدول topup_codes.
    - يرجع dict:
      {"ok": True,  "points": 100} لو نجح
      {"ok": False, "reason": "not_found" } لو الكود غير موجود
      {"ok": False, "reason": "used"      } لو الكود مستخدم سابقاً
      {"ok": False, "reason": "error", "error": "..."} لو حصل خطأ آخر
    """
    db: Session = SessionLocal()
    try:
        q = db.query(TopupCode).with_for_update()
        code_row = q.filter(TopupCode.code == code).first()

        if not code_row:
            return {"ok": False, "reason": "not_found"}

        if code_row.is_used:
            return {"ok": False, "reason": "used"}

        code_row.is_used = True
        code_row.used_by = telegram_id
        code_row.used_at = datetime.utcnow()
        points = code_row.points

        db.add(code_row)
        db.commit()

        return {"ok": True, "points": points}
    except Exception as e:
        logger.exception("redeem_code_in_db error: %s", e)
        db.rollback()
        return {"ok": False, "reason": "error", "error": str(e)}
    finally:
        db.close()


# =============== /start ===============

def start(update: Update, context: CallbackContext) -> None:
    """رسالة ترحيب بسيطة مع توضيح الأوامر المتاحة + الأزرار."""
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات للقصص.\n\n"
        "المميزات المتاحة حالياً:\n"
        "1️⃣ ✍️ كتابة قصة جديدة بالذكاء الاصطناعي — /write\n"
        "2️⃣ 📤 نشر قصة من كتابتك (نص أو PDF، حد أدنى ~1000 كلمة) — /publish\n"
        "3️⃣ 🎬 إنتاج فيديو بالذكاء الاصطناعي (Runway) — /video\n"
        "4️⃣ 📥 استعلام عن فيديو سابق برقم الطلب — /video_status\n"
        "5️⃣ 🖼 إنشاء صورة بالذكاء الاصطناعي — /image\n"
        "6️⃣ 💰 عرض الأسعار والنقاط — /pricing\n"
        "7️⃣ 💳 عرض رصيد المحفظة — /wallet\n"
        "8️⃣ 🎟 شحن المحفظة برمز من سلة — /redeem\n\n"
        "اختر من الأزرار بالأسفل أو استخدم الأوامر.",
        reply_markup=MAIN_KEYBOARD,
    )

#==================== نظام الأسعار==============================

def pricing_command(update: Update, context: CallbackContext) -> None:
    """عرض جدول الأسعار والنقاط."""
    pricing_text = get_pricing_text()
    update.message.reply_text(
        pricing_text,
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

# =============== أوامر المحفظة والشحن ===============

def wallet_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    user_id = user.id
    balance = get_user_balance(user_id)

    msg = (
        f"💳 *محفظتك في مرويات*\n\n"
        f"🔢 رصيدك الحالي: *{balance}* نقطة.\n\n"
        "لشحن المحفظة:\n"
        "1️⃣ اشترِ *كود شحن* من متجر مرويات في سلة (حسب الباقة: 50 / 100 / 150 / 200 نقطة).\n"
        "2️⃣ سيصلك رمز الشحن في رسالة من سلة.\n"
        "3️⃣ ادخل هنا واستخدم الأمر /redeem أو زر 🎟 شحن برمز من سلة.\n"
        "4️⃣ أرسل الكود، ولو كان صحيحًا وغير مستخدم ستُضاف النقاط إلى محفظتك.\n"
    )
    update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


def redeem_command(update: Update, context: CallbackContext) -> int:
    """
    بدء عملية شحن المحفظة برمز من سلة.
    """
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "🎟 لشحن محفظتك برمز من سلة، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /redeem هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "🎟 جميل! أرسل الآن *رمز الشحن* الذي اشتريته من متجر سلة.\n\n"
        "مثال (الشكل فقط، ليس كودًا حقيقياً):\n"
        "`MRW-100-XYZ111`\n\n"
        "تأكد من نسخه كما هو تمامًا.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_REDEEM_CODE


def handle_redeem_code(update: Update, context: CallbackContext) -> int:
    """
    يستقبل كود الشحن، يتحقق منه في قاعدة البيانات، ويضيف النقاط إن كان صحيحًا ولم يُستخدم من قبل.
    """
    raw_code = (update.message.text or "").strip()
    if not raw_code:
        update.message.reply_text(
            "❗ لم أستطع قراءة الكود، أعد إرساله من فضلك."
        )
        return STATE_REDEEM_CODE

    code = raw_code.strip().upper()
    user_id = get_user_id(update)

    result = redeem_code_in_db(code, user_id)

    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "not_found":
            update.message.reply_text(
                "❌ هذا الرمز غير صحيح أو غير مسجّل في النظام.\n"
                "تأكد أنك نسخته بالضبط من رسالة سلة."
            )
            return STATE_REDEEM_CODE
        elif reason == "used":
            update.message.reply_text(
                "⚠️ هذا الرمز تم استخدامه من قبل، ولا يمكن استعماله مرة أخرى."
            )
            return ConversationHandler.END
        else:
            update.message.reply_text(
                "⚠️ حدث خطأ أثناء محاولة تفعيل الكود. جرّب لاحقاً أو تواصل مع الدعم."
            )
            return ConversationHandler.END

    # نجح ✅
    points = result["points"]
    new_balance = add_user_points(user_id, points)

    update.message.reply_text(
        f"✅ تم شحن محفظتك بنجاح!\n"
        f"🪙 تم إضافة *{points}* نقطة إلى رصيدك.\n"
        f"🔢 رصيدك الجديد: *{new_balance}* نقطة.\n\n"
        "استمتع باستخدام خدمات مرويات 🌟",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END

#====================================== القصص / النشر / الفيديو / الصور =============================

def write_command(update: Update, context: CallbackContext) -> int:
    """يبدأ محادثة إنشاء قصة جديدة: أولاً يسأل عن نوع القصة."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "✍️ لإنشاء قصة جديدة، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /write هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "✨ أهلاً بك في مختبر مرويات لكتابة القصص.\n\n"
        "أولاً، اختر نوع القصة التي تريدها:",
        reply_markup=GENRE_KEYBOARD,
    )
    return STATE_STORY_GENRE


def handle_story_genre(update: Update, context: CallbackContext) -> int:
    """يستقبل نوع القصة من المستخدم ثم يطلب منه وصف الفكرة."""
    genre_text = (update.message.text or "").strip()
    context.user_data["story_genre"] = genre_text

    update.message.reply_text(
        "رائع! الآن اكتب لي *فكرة القصة* في رسالة واحدة، مثلاً:\n"
        "• من هو البطل أو البطلة؟\n"
        "• أين تدور الأحداث (المكان/الزمن)؟\n"
        "• ما المشكلة أو اللغز أو الهدف الرئيسي في القصة؟\n\n"
        "كلما كانت فكرتك أوضح، كانت القصة أفضل 🌟",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return STATE_STORY_BRIEF


def generate_story_with_openai(brief: str, genre: str, username: str = "") -> str:
    """يستدعي OpenAI لكتابة قصة عربية بناءً على النوع + الوصف."""
    if client is None:
        return "❌ لا يوجد إعداد لمفتاح OpenAI حالياً (OPENAI_API_KEY)."

    user_prompt = (
        f"نوع القصة المطلوب: {genre}\n\n"
        f"هذه فكرة القصة من المستخدم (@{username}):\n\n"
        f"{brief}\n\n"
        "اكتب قصة كاملة وفق هذه الفكرة وهذا النوع. "
        "تأكد أن أجواء القصة وأسلوبها يناسبان نوع القصة المكتوب في الأعلى."
    )

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
        )
        story = completion.choices[0].message.content.strip()
        return story
    except Exception as e:
        logger.exception("OpenAI error: %s", e)
        return "❌ حدث خطأ أثناء الاتصال بخدمة الذكاء الاصطناعي. حاول مرة أخرى لاحقاً."


def receive_story_brief(update: Update, context: CallbackContext) -> int:
    """يستقبل وصف القصة، يتحقق من رصيد النقاط، يستدعي OpenAI، ويرسل القصة الناتجة للمستخدم."""
    brief = (update.message.text or "").strip()
    genre = context.user_data.get("story_genre", "غير محدد")

    if not brief:
        update.message.reply_text("❗ لم أستطع قراءة وصف القصة، أعد كتابته من فضلك.")
        return STATE_STORY_BRIEF

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    # التأكد من وجود نقاط كافية للقصة
    if not require_and_deduct(update, STORY_COST_POINTS):
        return ConversationHandler.END

    update.message.reply_text(
        f"⏳ جميل! سأكتب الآن قصة من نوع: {genre}\n"
        "بناءً على فكرتك... قد يستغرق ذلك بضع ثوانٍ.",
    )

    story_text = generate_story_with_openai(brief, genre=genre, username=username)

    if story_text.startswith("❌"):
        update.message.reply_text(story_text, reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    MAX_LEN = 3500
    chunks = wrap(story_text, MAX_LEN, break_long_words=False, replace_whitespace=False)

    update.message.reply_text("✅ تم إنشاء القصة! إليك النص:")

    for i, chunk in enumerate(chunks, start=1):
        header = f"الجزء {i}:\n\n" if len(chunks) > 1 else ""
        update.message.reply_text(header + chunk)

    update.message.reply_text(
        "🎉 انتهينا! إذا أعجبتك القصة يمكنك حفظها أو مشاركتها.\n"
        "لإنشاء قصة جديدة استخدم الأمر /write أو الزر من الأسفل.",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END


def review_story_with_openai(text: str, username: str = ""):
    """
    يرسل نص القصة إلى OpenAI لمراجعته.
    يُرجع dict فيه:
      approved (bool), word_count (int), title (str), reasons (str), suggestions (str)
    """
    if client is None:
        return {
            "approved": False,
            "word_count": len(text.split()),
            "title": "",
            "reasons": "لا يوجد إعداد لمفتاح OpenAI.",
            "suggestions": "",
        }

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": f"هذه قصة من المستخدم @{username}:\n\n{text}"},
            ],
            temperature=0.3,
        )
        raw = completion.choices[0].message.content.strip()

        data = json.loads(raw)
        data.setdefault("approved", False)
        data.setdefault("word_count", len(text.split()))
        data.setdefault("title", "")
        data.setdefault("reasons", "")
        data.setdefault("suggestions", "")
        return data

    except Exception as e:
        logger.exception("OpenAI review error: %s", e)
        return {
            "approved": False,
            "word_count": len(text.split()),
            "title": "",
            "reasons": "حدث خطأ أثناء مراجعة القصة بالذكاء الاصطناعي.",
            "suggestions": "",
        }


def publish_command(update: Update, context: CallbackContext) -> int:
    """يبدأ محادثة استقبال قصة من المستخدم."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "📤 لنشر قصة من كتابتك، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /publish هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "📤 جميل! سنقوم الآن باستقبال قصتك.\n\n"
        "يمكنك:\n"
        "• إرسال نص القصة كاملة في *رسالة واحدة*.\n"
        "• أو إرسال ملف *PDF* يحتوي على القصة.\n\n"
        "الحد الأدنى التقريبي للنشر هو 1000 كلمة.\n"
        "بعد الإرسال سأقوم بتحليل القصة وإخبارك هل تم قبولها للنشر في 'قصص المجتمع'.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return STATE_PUBLISH_STORY


def handle_pdf_story(update: Update, context: CallbackContext) -> int:
    """يستقبل ملف PDF من المستخدم، يستخرج النص، يراجعه، ثم ينشره إذا كان مناسباً."""
    doc = update.message.document

    if not doc or doc.mime_type != "application/pdf":
        update.message.reply_text("❗ من فضلك أرسل ملف PDF صالح يحتوي على القصة.")
        return STATE_PUBLISH_STORY

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text("📥 تم استلام ملف PDF، جاري استخلاص النص وتحليله...")

    try:
        file = doc.get_file()
        bio = BytesIO()
        file.download(out=bio)
        bio.seek(0)

        reader = PyPDF2.PdfReader(bio)
        full_text = ""
        for page in reader.pages:
            page_text = page.extract_text() or ""
            full_text += page_text + "\n"

    except Exception as e:
        logger.exception("PDF read error: %s", e)
        update.message.reply_text("❌ حدث خطأ أثناء قراءة ملف الـPDF. تأكد أن الملف نصي وليس صوراً فقط.")
        return ConversationHandler.END

    cleaned_text = full_text.strip()
    if not cleaned_text:
        update.message.reply_text("❌ لم أتمكن من استخراج أي نص من ملف الـPDF. ربما يكون عبارة عن صور فقط.")
        return ConversationHandler.END

    MAX_CHARS_FOR_REVIEW = 15000
    if len(cleaned_text) > MAX_CHARS_FOR_REVIEW:
        cleaned_text = cleaned_text[:MAX_CHARS_FOR_REVIEW]

    review = review_story_with_openai(cleaned_text, username=username)
    approved = bool(review.get("approved"))
    word_count = int(review.get("word_count") or len(cleaned_text.split()))
    title = review.get("title") or "قصة من المجتمع"
    reasons = review.get("reasons") or ""
    suggestions = review.get("suggestions") or ""

    if not approved:
        msg = (
            f"🔎 تم تحليل قصتك من ملف الـPDF.\n"
            f"📊 عدد الكلمات التقريبي: *{word_count}* كلمة.\n\n"
            "🚫 النتيجة: *غير جاهزة للنشر حالياً*.\n"
        )
        if reasons:
            msg += f"\nالسبب الرئيسي:\n{reasons}\n"
        if suggestions:
            msg += f"\nبعض الاقتراحات للتحسين:\n{suggestions}\n"
        update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    msg = (
        f"✅ تم تحليل قصتك من ملف الـPDF.\n"
        f"📊 عدد الكلمات التقريبي: *{word_count}* كلمة.\n"
        "📣 النتيجة: *صالحة للنشر في قسم قصص المجتمع*.\n\n"
        "🚀 سيتم الآن نشر ملف الـPDF في مجتمع مرويات باسمك."
    )
    update.message.reply_text(msg, parse_mode="Markdown")

    if COMMUNITY_CHAT_ID:
        try:
            caption = (
                f"📖 *{title}*\n"
                f"✍️ من القارئ: @{username}\n\n"
                "قسم: قصص المجتمع — منصة مرويات."
            )
            context.bot.send_document(
                chat_id=int(COMMUNITY_CHAT_ID),
                document=doc.file_id,
                caption=caption,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.exception("Error sending PDF to community: %s", e)
            update.message.reply_text(
                "⚠️ تم قبول القصة، لكن حدث خطأ أثناء نشرها في المجتمع. "
                "سأخبر الإدارة لمراجعة الأمر.",
                reply_markup=MAIN_KEYBOARD,
            )
            return ConversationHandler.END
    else:
        update.message.reply_text(
            "✅ القصة مقبولة، لكن لم يتم ضبط COMMUNITY_CHAT_ID في الإعدادات، "
            "لذا لن أستطيع النشر تلقائياً.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "🎉 تم نشر قصتك في مجتمع مرويات بنجاح.\n"
        "شكرًا لمشاركتك 🌟",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


def receive_publish_story(update: Update, context: CallbackContext) -> int:
    """يستقبل نص القصة من المستخدم ويتحقق منه ويُراجعه بالذكاء الاصطناعي."""
    text = (update.message.text or "").strip()

    if not text:
        update.message.reply_text("لم أستطع قراءة نص القصة، أعد الإرسال من فضلك.")
        return STATE_PUBLISH_STORY

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text("🔎 جاري تحليل قصتك والتأكد من جاهزيتها للنشر...")

    review = review_story_with_openai(text, username=username)
    approved = bool(review.get("approved"))
    word_count = int(review.get("word_count") or len(text.split()))
    title = review.get("title") or "قصة من المجتمع"
    reasons = review.get("reasons") or ""
    suggestions = review.get("suggestions") or ""

    if not approved:
        msg = (
            f"📊 عدد كلمات قصتك هو *{word_count}* كلمة تقريباً.\n\n"
            "🚫 النتيجة: *غير جاهزة للنشر حالياً*.\n"
        )
        if reasons:
            msg += f"\nالسبب الرئيسي:\n{reasons}\n"
        if suggestions:
            msg += f"\nبعض الاقتراحات للتحسين:\n{suggestions}\n"
        update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    context.user_data["last_published_story"] = text
    context.user_data["last_published_words"] = word_count

    msg = (
        f"✅ تم قبول قصتك للنشر!\n"
        f"📊 عدد الكلمات التقريبي: *{word_count}* كلمة.\n\n"
        "حالياً النشر التلقائي للنصوص غير مفعّل (يمكن لاحقاً تحويلها تلقائياً إلى PDF ونشرها).\n"
        "شكرًا لمشاركتك 🌟"
    )
    update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

    return ConversationHandler.END

# =============== فيديو بالذكاء الاصطناعي (Runway) ===============

def video_command(update: Update, context: CallbackContext) -> int:
    """بدء محادثة إنتاج فيديو: طلب فكرة الفيديو أولاً."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "🎬 لإنتاج فيديو بالذكاء الاصطناعي، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /video هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "🎬 أهلاً بك في مختبر الفيديو في مرويات.\n\n"
        "اكتب لي فكرة الفيديو التي تريدها، مثلاً:\n"
        "• مشهد غموض في مدينة الرياض ليلاً مع ضباب.\n"
        "• طفل يمشي في مكتبة قديمة، كاميرا من خلفه.\n"
        "• لقطة سينمائية لجزيرة مهجورة وقت الغروب.\n\n"
        "بعد ذلك سأطلب منك تحديد مدة الفيديو بالثواني.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_VIDEO_IDEA


def refine_video_prompt_with_openai(idea: str, extra_info: str = "", username: str = ""):
    """يستخدم OpenAI إما لطلب تفاصيل إضافية أو لصنع برومبت نهائي للفيديو."""
    if client is None:
        return {"status": "error", "error": "No OPENAI client configured."}

    user_content = f"فكرة الفيديو من المستخدم @{username}:\n{idea}"
    if extra_info:
        user_content += f"\n\nمعلومات إضافية:\n{extra_info}"

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": VIDEO_PROMPT_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.5,
        )
        raw = completion.choices[0].message.content.strip()
        data = json.loads(raw)
        return data
    except Exception as e:
        logger.exception("OpenAI video prompt error: %s", e)
        return {"status": "error", "error": "حدث خطأ أثناء تحليل فكرة الفيديو."}


def _map_duration_to_runway(seconds: int) -> int:
    """
    Runway text_to_video يدعم فقط القيم: 4 أو 6 أو 8 ثواني.
    نحول اختيار المستخدم (5–20 ثانية) لأقرب قيمة مسموحة.
    """
    if seconds <= 5:
        return 4
    elif seconds <= 10:
        return 6
    else:
        return 8


def create_runway_video_generation(prompt: str, duration_seconds: int = 10, aspect_ratio: str = "1280:720"):
    """يرسل طلب إنشاء فيديو نصي إلى Runway (text_to_video)."""
    if not RUNWAY_API_KEY:
        return {"ok": False, "error": "RUNWAY_API_KEY is not set."}

    mapped_duration = _map_duration_to_runway(duration_seconds)

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": RUNWAY_API_VERSION,
    }

    payload = {
        "model": RUNWAY_MODEL,
        "promptText": prompt,
        "ratio": aspect_ratio,   # مثل 1280:720 أو 1080:1920
        "audio": False,
        "duration": mapped_duration,
    }

    try:
        resp = requests.post(RUNWAY_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"Runway API error: {resp.status_code} {resp.text}"}
        data = resp.json()
        return {"ok": True, "data": data}
    except Exception as e:
        logger.exception("Runway API error: %s", e)
        return {"ok": False, "error": "فشل الاتصال بـ Runway API."}


def get_runway_task_detail(task_id: str):
    """استدعاء GET /v1/tasks/{id} للحصول على حالة المهمة والكائن كامل."""
    if not RUNWAY_API_KEY:
        return {"ok": False, "error": "RUNWAY_API_KEY is not set."}

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "X-Runway-Version": RUNWAY_API_VERSION,
    }

    url = f"{RUNWAY_TASKS_URL.rstrip('/')}/{task_id}"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"Runway task detail error: {resp.status_code} {resp.text}",
                "status_code": resp.status_code,
            }
        return {"ok": True, "data": resp.json()}
    except Exception as e:
        logger.exception("Runway task detail error: %s", e)
        return {"ok": False, "error": "فشل جلب حالة مهمة Runway."}


def wait_for_runway_task(task_id: str, max_wait: int = 60, poll_interval: int = 6):
    """
    ينتظر حتى تنتهي المهمة على Runway أو ينتهي max_wait ثانية.
    يرجع dict فيه:
      ok: bool (True لو SUCCEEDED)
      status: حالة المهمة من Runway
      data: الكائن الكامل للمهمة (JSON)
    """
    start = time.time()
    last_data = None
    while time.time() - start < max_wait:
        result = get_runway_task_detail(task_id)
        if not result.get("ok"):
            return result

        data = result["data"]
        last_data = data
        status = str(data.get("status", "")).upper()

        if status in ("SUCCEEDED", "FAILED", "ABORTED", "CANCELED", "CANCELLED"):
            return {
                "ok": status == "SUCCEEDED",
                "status": status,
                "data": data,
            }

        # ما زالت PENDING / RUNNING / THROTTLED
        time.sleep(poll_interval)

    # انتهى الوقت ولم تنته المهمة
    return {
        "ok": False,
        "status": str(last_data.get("status")) if isinstance(last_data, dict) else "UNKNOWN",
        "data": last_data,
        "error": "TIMEOUT",
    }


def extract_runway_video_url(task_data: dict):
    """
    نحاول استخراج رابط فيديو (url أو uri يبدأ بـ http) من كائن المهمة.
    """
    if isinstance(task_data, list):
        for item in task_data:
            if isinstance(item, str) and item.startswith("http"):
                return item
        task_root = {"_root": task_data}
    elif isinstance(task_data, dict):
        task_root = task_data
    else:
        return None

    output_val = task_root.get("output")
    if isinstance(output_val, str) and output_val.startswith("http"):
        return output_val
    if isinstance(output_val, list):
        for item in output_val:
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, dict):
                if "url" in item or "uri" in item:
                    val = item.get("url") or item.get("uri")
                    if isinstance(val, str) and val.startswith("http"):
                        return val

    candidates = []

    def walk(obj):
        if isinstance(obj, dict):
            if "uri" in obj or "url" in obj:
                val = obj.get("uri") or obj.get("url")
                candidates.append(val)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            if obj.startswith("http"):
                candidates.append(obj)

    walk(task_root)

    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c

    return None


def send_runway_request_and_reply(
    update: Update,
    context: CallbackContext,
    final_prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
):
    """
    - ترسل الطلب إلى Runway
    - تعرض رقم المهمة
    - تحاول الانتظار حتى انتهاء المهمة (حتى ٦٠ ثانية)
    - لو نجحت ترسل الفيديو / الرابط للمستخدم
    """
    runway_resp = create_runway_video_generation(
        prompt=final_prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
    )

    if not runway_resp.get("ok"):
        update.message.reply_text(
            f"⚠️ تم تجهيز البرومبت، لكن حدث خطأ عند الإرسال إلى Runway:\n{runway_resp.get('error')}",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    data = runway_resp.get("data", {})
    gen_id = data.get("id", "غير معروف")

    update.message.reply_text(
        "🚀 تم إرسال طلب الفيديو إلى Runway بنجاح.\n"
        f"🆔 رقم الطلب: `{gen_id}`",
        parse_mode="Markdown",
    )

    update.message.reply_text("⏳ جاري متابعة حالة المهمة على Runway، انتظر قليلاً...")

    wait_result = wait_for_runway_task(gen_id, max_wait=60, poll_interval=6)

    if not wait_result.get("ok"):
        status = wait_result.get("status")
        if status:
            msg = (
                f"ℹ️ حالة المهمة الحالية على Runway: *{status}*.\n"
                "قد يستمر المعالجة هناك، يمكنك متابعة التقدم من لوحة Runway باستخدام رقم الطلب."
            )
            update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        else:
            update.message.reply_text(
                "⚠️ لم أستطع التأكد من انتهاء المهمة على Runway الآن. "
                "استخدم رقم الطلب لمتابعتها في لوحة Runway.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    task_data = wait_result.get("data") or {}
    video_url = extract_runway_video_url(task_data)

    if video_url:
        try:
            update.message.reply_text("🎉 تم إنشاء الفيديو على Runway! سأرسله لك الآن...")
            context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_url,
                caption="🎬 الفيديو الناتج من Runway.",
            )
        except Exception as e:
            logger.exception("Telegram send_video error: %s", e)
            update.message.reply_text(
                "🎬 تم إنشاء الفيديو، لكن تعذر إرساله كملف على تيليجرام.\n"
                f"هذا رابط الفيديو:\n{video_url}",
                reply_markup=MAIN_KEYBOARD,
            )
    else:
        pretty = json.dumps(task_data, ensure_ascii=False, indent=2)
        update.message.reply_text(
            "✅ المهمة انتهت بنجاح في Runway، لكن لم أستطع العثور على رابط الفيديو بشكل واضح.\n"
            "هذا الكائن المرسل من Runway (يمكنك مراجعته أو إرساله للمطور):\n"
            f"```json\n{pretty}\n```",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_video_idea(update: Update, context: CallbackContext) -> int:
    """يستقبل فكرة الفيديو ثم يطلب من المستخدم اختيار المدة."""
    idea = (update.message.text or "").strip()
    if not idea:
        update.message.reply_text("❗ لم أستطع قراءة فكرة الفيديو، أعد كتابتها من فضلك.")
        return STATE_VIDEO_IDEA

    context.user_data["video_idea"] = idea

    duration_keyboard = ReplyKeyboardMarkup(
        [["5", "10", "15", "20"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    update.message.reply_text(
        "⏱ كم مدة الفيديو التي تريدها (بالثواني)؟\n"
        "يمكنك اختيار من الأزرار أو كتابة رقم بين 5 و 20.",
        reply_markup=duration_keyboard,
    )

    return STATE_VIDEO_DURATION


def handle_video_duration(update: Update, context: CallbackContext) -> int:
    """يستقبل مدة الفيديو بالثواني ثم يستدعي OpenAI لتجهيز البرومبت ثم Runway مع خصم النقاط."""
    text = (update.message.text or "").strip()

    try:
        seconds = int(text)
    except ValueError:
        update.message.reply_text(
            "من فضلك أرسل رقم صحيح للمدة بالثواني، مثلاً 10 أو 15."
        )
        return STATE_VIDEO_DURATION

    if seconds < 5 or seconds > 20:
        update.message.reply_text(
            "يفضل أن تكون مدة الفيديو بين 5 و 20 ثانية.\n"
            "أرسل رقم داخل هذا النطاق."
        )
        return STATE_VIDEO_DURATION

    idea = context.user_data.get("video_idea", "")
    if not idea:
        update.message.reply_text(
            "❌ فقدت فكرة الفيديو، لنعد من البداية. اكتب /video مرة أخرى.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    context.user_data["video_duration_seconds"] = seconds

    user = update.effective_user
    username = user.username or user.first_name or "مستخدم"

    update.message.reply_text("🔍 جاري تحليل فكرتك وتجهيز برومبت الفيديو...")

    extra_info = f"المستخدم يريد مدة تقريبية للفيديو تبلغ {seconds} ثانية."
    result = refine_video_prompt_with_openai(idea, extra_info=extra_info, username=username)
    status = result.get("status")

    if status == "need_more":
        questions = result.get("questions", [])
        if not questions:
            update.message.reply_text(
                "أحتاج بعض التفاصيل الإضافية عن الفيديو (الشخصيات، المكان، أسلوب التصوير، المزاج...). اكتبها في رسالة واحدة.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            msg = "حتى أصنع برومبت فيديو قوي، أحتاج منك توضح لي هذه النقاط:\n\n"
            for q in questions:
                msg += f"- {q}\n"
            msg += "\n✍️ أرسل إجاباتك في رسالة واحدة."
            update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())

        return STATE_VIDEO_CLARIFY

    if status == "ok":
        final_prompt = result.get("final_prompt", "")
        duration_seconds = int(result.get("duration_seconds", seconds))
        aspect_ratio = "1280:720"

        if not final_prompt:
            update.message.reply_text(
                "حدث خطأ في توليد برومبت الفيديو. حاول وصف فكرتك مرة أخرى بشكل أوضح.",
                reply_markup=MAIN_KEYBOARD,
            )
            return ConversationHandler.END

        needed_points = get_video_cost_points(duration_seconds)
        if not require_and_deduct(update, needed_points):
            return ConversationHandler.END

        update.message.reply_text(
            "✅ تم توليد برومبت احترافي للفيديو.\n"
            "📤 الآن سأرسل الطلب إلى Runway لإنشاء الفيديو ومتابعة حالته...",
        )

        send_runway_request_and_reply(
            update=update,
            context=context,
            final_prompt=final_prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
        )

        return ConversationHandler.END

    update.message.reply_text(
        "❌ حدث خطأ أثناء تحليل فكرة الفيديو. حاول مرة أخرى لاحقاً.",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END


def handle_video_clarify(update: Update, context: CallbackContext) -> int:
    """يستقبل تفاصيل إضافية عن الفيديو بعد أسئلة التوضيح ثم يرسل الطلب إلى Runway مع خصم النقاط."""
    extra = (update.message.text or "").strip()
    idea = context.user_data.get("video_idea", "")
    seconds = context.user_data.get("video_duration_seconds", 10)

    if not extra:
        update.message.reply_text("❗ لم أستطع قراءة إجاباتك، أعد إرسالها من فضلك.")
        return STATE_VIDEO_CLARIFY

    user = update.effective_user
    username = user.username or user.first_name or "مستخدم"

    update.message.reply_text("🔧 شكراً للتفاصيل! جاري تجهيز برومبت الفيديو النهائي...")

    extra_info = extra + f"\n\nمدة الفيديو المرغوبة تقريباً: {seconds} ثانية."
    result = refine_video_prompt_with_openai(idea, extra_info=extra_info, username=username)
    status = result.get("status")

    if status != "ok":
        update.message.reply_text(
            "❌ لم أتمكن من إنشاء برومبت نهائي للفيديو. حاول وصف فكرتك مرة أخرى من البداية.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    final_prompt = result.get("final_prompt", "")
    duration_seconds = int(result.get("duration_seconds", seconds))
    aspect_ratio = "1280:720"

    if not final_prompt:
        update.message.reply_text(
            "حدث خطأ في توليد برومبت الفيديو. حاول وصف فكرتك مرة أخرى.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    needed_points = get_video_cost_points(duration_seconds)
    if not require_and_deduct(update, needed_points):
        return ConversationHandler.END

    update.message.reply_text(
        "✅ تم تجهيز برومبت احترافي للفيديو بعد الأخذ بتفاصيلك.\n"
        "📤 الآن سأرسل الطلب إلى Runway لإنشاء الفيديو ومتابعة حالته...",
    )

    send_runway_request_and_reply(
        update=update,
        context=context,
        final_prompt=final_prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
    )

    return ConversationHandler.END


def video_status_command(update: Update, context: CallbackContext) -> int:
    """يطلب من المستخدم إدخال رقم طلب Runway للاستعلام عنه."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "📥 للاستعلام عن حالة فيديو سابق، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /video_status هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "📥 أرسل الآن *رقم الطلب* الذي حصلت عليه من Runway (على شكل UUID):\n"
        "`103d6a74-a651-4a6d-ada5-df8c640117ec` كمثال.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_VIDEO_STATUS_ID


def handle_video_status(update: Update, context: CallbackContext) -> int:
    """يستقبل رقم الطلب، يجلب حالة المهمة من Runway، ويحاول إرسال الفيديو إن وُجد."""
    task_id = (update.message.text or "").strip()

    if not task_id:
        update.message.reply_text("❗ لم أستطع قراءة رقم الطلب، أرسله مرة أخرى.")
        return STATE_VIDEO_STATUS_ID

    update.message.reply_text(
        f"🔎 جاري الاستعلام عن حالة الطلب:\n`{task_id}`",
        parse_mode="Markdown",
    )

    result = get_runway_task_detail(task_id)
    if not result.get("ok"):
        update.message.reply_text(
            f"⚠️ حدث خطأ أثناء جلب حالة الطلب من Runway:\n{result.get('error')}",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    data = result.get("data", {})
    status = str(data.get("status", "غير معروف")).upper()

    base_msg = (
        f"ℹ️ حالة مهمة الفيديو على Runway:\n\n"
        f"🆔 رقم الطلب: `{task_id}`\n"
        f"📌 الحالة الحالية: *{status}*"
    )

    if status == "SUCCEEDED":
        video_url = extract_runway_video_url(data)
        if video_url:
            try:
                update.message.reply_text(
                    base_msg + "\n\n🎉 تم العثور على الفيديو، جاري إرساله...",
                    parse_mode="Markdown",
                )
                update.message.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_url,
                    caption="🎬 الفيديو الناتج من Runway لهذا الطلب.",
                )
            except Exception as e:
                logger.exception("Telegram send_video (status) error: %s", e)
                update.message.reply_text(
                    base_msg
                    + "\n\n🎬 تم إنشاء الفيديو، لكن تعذر إرساله كملف على تيليجرام.\n"
                    f"هذا رابط الفيديو:\n{video_url}",
                    parse_mode="Markdown",
                    reply_markup=MAIN_KEYBOARD,
                )
        else:
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            update.message.reply_text(
                base_msg
                + "\n\n✅ المهمة ناجحة، لكن لم أستطع العثور على رابط الفيديو بشكل واضح.\n"
                "هذا الكائن المرسل من Runway:\n"
                f"```json\n{pretty}\n```",
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            )
    else:
        update.message.reply_text(
            base_msg
            + "\n\nقد تكون المهمة ما زالت قيد التنفيذ أو فشلت. "
              "يمكنك التحقق أيضاً من لوحة Runway مباشرة.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )

    return ConversationHandler.END

# =============== صور بالذكاء الاصطناعي (OpenAI Images) ===============

def image_command(update: Update, context: CallbackContext) -> int:
    """بدء محادثة إنشاء صورة."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "🖼 لإنشاء صورة بالذكاء الاصطناعي، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /image هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "🖼 رائع! اكتب وصف الصورة التي تريدها.\n"
        "مثلاً:\n"
        "• غلاف لقصة غموض في مدينة الرياض ليلاً مع ضباب.\n"
        "• طفل يقرأ كتاباً في مكتبة قديمة، أسلوب كرتوني.\n"
        "• منظر سينمائي لجزيرة مهجورة وقت الغروب.\n\n"
        "سأحوّل وصفك إلى برومبت احترافي وأنتج لك صورة.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_IMAGE_PROMPT


def generate_image_prompt_with_openai(description: str) -> str:
    """يحوّل وصف بالعربية إلى برومبت إنجليزي احترافي للصور."""
    if client is None:
        return ""

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": IMAGE_PROMPT_SYSTEM},
                {"role": "user", "content": description},
            ],
            temperature=0.7,
        )
        prompt = completion.choices[0].message.content.strip()
        return prompt
    except Exception as e:
        logger.exception("OpenAI image prompt error: %s", e)
        return ""


def handle_image_prompt(update: Update, context: CallbackContext) -> int:
    """يستقبل وصف الصورة، يتحقق من رصيد النقاط، ثم ينتج صورة باستخدام OpenAI Images."""
    desc = (update.message.text or "").strip()
    if not desc:
        update.message.reply_text("❗ لم أستطع قراءة وصف الصورة، أعد كتابته من فضلك.")
        return STATE_IMAGE_PROMPT

    if not require_and_deduct(update, IMAGE_COST_POINTS):
        return ConversationHandler.END

    update.message.reply_text("🎨 جاري تحويل وصفك إلى برومبت احترافي وإنشاء الصورة...")

    refined_prompt = generate_image_prompt_with_openai(desc)
    if not refined_prompt:
        update.message.reply_text(
            "❌ حدث خطأ أثناء تجهيز برومبت الصورة. حاول مرة أخرى.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    if client is None:
        update.message.reply_text(
            "❌ إعداد OpenAI Images غير مكتمل حالياً.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    try:
        img_resp = client.images.generate(
            model="gpt-image-1",
            prompt=refined_prompt,
            size="1024x1024",
            n=1,
        )

        if not img_resp.data or not getattr(img_resp.data[0], "url", None):
            raise RuntimeError("No URL returned from OpenAI Images")

        image_url = img_resp.data[0].url

    except Exception as e:
        logger.exception("OpenAI image generation error: %s", e)
        update.message.reply_text(
            f"❌ حدث خطأ أثناء توليد الصورة من OpenAI:\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    caption = (
        "🖼 هذه هي الصورة الناتجة عن وصفك.\n"
        "إذا أعجبتك، يمكنك حفظها أو استخدامها كغلاف لقصة في مرويات."
    )
    update.message.reply_photo(photo=image_url, caption=caption, reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# =============== /cancel — إلغاء أي محادثة ===============

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "تم إلغاء العملية. يمكنك البدء من جديد بالأزرار أو بالأوامر:\n"
        "/write أو /publish أو /video أو /video_status أو /image أو /redeem.",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END

# =============== main ===============

def main() -> None:
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("pricing", pricing_command))
    dp.add_handler(CommandHandler("wallet", wallet_command))
    dp.add_handler(CommandHandler("redeem", redeem_command))

    dp.add_handler(
        MessageHandler(
            Filters.regex("^💳 المحفظة / الشحن$"),
            wallet_command,
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.regex("^💰 الأسعار والنقاط$"),
            pricing_command,
        )
    )
    dp.add_handler(
        MessageHandler(
            Filters.regex("^🎟 شحن برمز من سلة$"),
            redeem_command,
        )
    )

    # كتابة قصة بالذكاء الاصطناعي
    story_conv = ConversationHandler(
        entry_points=[
            CommandHandler("write", write_command),
            MessageHandler(
                Filters.regex("^✍️ كتابة قصة بالذكاء الاصطناعي$"),
                write_command,
            ),
        ],
        states={
            STATE_STORY_GENRE: [
                MessageHandler(Filters.text & ~Filters.command, handle_story_genre)
            ],
            STATE_STORY_BRIEF: [
                MessageHandler(Filters.text & ~Filters.command, receive_story_brief)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(story_conv)

    # نشر قصة من كتابة المستخدم (نص أو PDF)
    publish_conv = ConversationHandler(
        entry_points=[
            CommandHandler("publish", publish_command),
            MessageHandler(
                Filters.regex("^📤 نشر قصة من كتابتك$"),
                publish_command,
            ),
        ],
        states={
            STATE_PUBLISH_STORY: [
                MessageHandler(Filters.document.pdf, handle_pdf_story),
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_publish_story,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(publish_conv)

    # إنتاج فيديو بالذكاء الاصطناعي
    video_conv = ConversationHandler(
        entry_points=[
            CommandHandler("video", video_command),
            MessageHandler(
                Filters.regex("^🎬 إنتاج فيديو بالذكاء الاصطناعي$"),
                video_command,
            ),
        ],
        states={
            STATE_VIDEO_IDEA: [
                MessageHandler(Filters.text & ~Filters.command, handle_video_idea)
            ],
            STATE_VIDEO_DURATION: [
                MessageHandler(Filters.text & ~Filters.command, handle_video_duration)
            ],
            STATE_VIDEO_CLARIFY: [
                MessageHandler(Filters.text & ~Filters.command, handle_video_clarify)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(video_conv)

    # استعلام عن فيديو سابق برقم الطلب
    video_status_conv = ConversationHandler(
        entry_points=[
            CommandHandler("video_status", video_status_command),
            MessageHandler(
                Filters.regex("^📥 استعلام عن فيديو سابق$"),
                video_status_command,
            ),
        ],
        states={
            STATE_VIDEO_STATUS_ID: [
                MessageHandler(Filters.text & ~Filters.command, handle_video_status)
            ],
        ],
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(video_status_conv)

    # إنشاء صورة بالذكاء الاصطناعي
    image_conv = ConversationHandler(
        entry_points=[
            CommandHandler("image", image_command),
            MessageHandler(
                Filters.regex("^🖼 إنشاء صورة بالذكاء الاصطناعي$"),
                image_command,
            ),
        ],
        states={
            STATE_IMAGE_PROMPT: [
                MessageHandler(Filters.text & ~Filters.command, handle_image_prompt)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(image_conv)

    # شحن برمز من سلة (محادثة)
    redeem_conv = ConversationHandler(
        entry_points=[
            CommandHandler("redeem", redeem_command),
            MessageHandler(
                Filters.regex("^🎟 شحن برمز من سلة$"),
                redeem_command,
            ),
        ],
        states={
            STATE_REDEEM_CODE: [
                MessageHandler(Filters.text & ~Filters.command, handle_redeem_code)
            ],
        ],
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(redeem_conv)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
