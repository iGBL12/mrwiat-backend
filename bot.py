# bot.py
import os
import logging
import json
import time
from io import BytesIO
from textwrap import wrap
from datetime import datetime
import re

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
from sqlalchemy.orm import Session
from database import Base, engine, SessionLocal
from models import User, Wallet, RedeemCode

# =============== الإعدادات العامة ===============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

# مفاتيح خدمة الفيديو بالذكاء الاصطناعي (Runway داخلياً)
RUNWAY_API_KEY = os.environ.get("RUNWAY_API_KEY")
RUNWAY_API_URL = os.environ.get(
    "RUNWAY_API_URL",
    "https://api.dev.runwayml.com/v1/text_to_video",
)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06")
RUNWAY_MODEL = os.environ.get("RUNWAY_MODEL", "veo3.1")
RUNWAY_TASKS_URL = os.environ.get(
    "RUNWAY_TASKS_URL",
    "https://api.dev.runwayml.com/v1/tasks",
)

COMMUNITY_CHAT_ID = os.environ.get("COMMUNITY_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Story generation / review will fail.")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

# تأكد من إنشاء الجداول
Base.metadata.create_all(bind=engine)

# ======== أسعار النقاط =========

IMAGE_COST_POINTS = 25        # صورة
STORY_COST_POINTS = 5         # قصة نصية

def get_video_cost_points(duration_seconds: int) -> int:
    if duration_seconds <= 5:
        return 30
    elif duration_seconds <= 10:
        return 60
    elif duration_seconds <= 15:
        return 85
    else:
        return 110

# =============== ثوابت الحالات في المحادثة ===============

STATE_STORY_GENRE = 1
STATE_STORY_BRIEF = 2
STATE_PUBLISH_STORY = 3
STATE_VIDEO_IDEA = 4
STATE_VIDEO_CLARIFY = 5
STATE_IMAGE_PROMPT = 6
STATE_VIDEO_DURATION = 7
STATE_VIDEO_STATUS_ID = 8
STATE_REDEEM_CODE = 9

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

GENRE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["غموض 🕵️‍♂️", "رعب 👻"],
        ["خيال علمي 🚀", "رومانسية 💕"],
        ["دراما 🎭", "مغامرة 🏝️"],
        ["نوع آخر"],
    ],
    resize_keyboard=True,
)

# =============== SYSTEM PROMPTS (داخلية لا يراها المستخدم) ===============

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
أنت خبير في صناعة برومبت احترافي لمولد فيديو بالذكاء الاصطناعي.

مهمتك:
1. استلام وصف لفكرة فيديو من المستخدم (غالباً بالعربية).
2. تقييم وضوح الفكرة.
3. إذا كانت الفكرة غير كافية، اطلب تفاصيل إضافية عن:
   - الشخصيات
   - المكان
   - أسلوب التصوير
   - المزاج
   - مدة الفيديو.
4. إذا كانت الفكرة كافية، أنشئ برومبت نهائي باللغة الإنجليزية، مفصل وواضح، وجاهز للإرسال لنموذج إنشاء الفيديو.

أعد النتيجة دائماً في صيغة JSON كما هو موضح سابقاً.
"""

IMAGE_PROMPT_SYSTEM = """
أنت مهندس برومبت للصور (Image Prompt Engineer) تعمل مع نموذج صور متقدم.

مهمتك:
- استلام وصف صورة من المستخدم (غالباً بالعربية).
- تحويله إلى برومبت باللغة الإنجليزية، مفصل وواضح، يناسب نموذج صور متقدم.
- أضف تفاصيل عن الإضاءة، الأسلوب الفني، زاوية الكاميرا إذا لزم.

أعد النتيجة كنص واحد فقط: البرومبت باللغة الإنجليزية بدون أي شرح إضافي.
"""

# =============== دوال المستخدم والمحفظة ===============

def get_user_id(update: Update) -> int:
    return update.effective_user.id


def myid_command(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        f"🔢 Telegram ID الخاص بك هو:\n`{user.id}`",
        parse_mode="Markdown",
    )


def _get_or_create_user_and_wallet(db: Session, tg_user) -> tuple[User, Wallet]:
    """يرجع User + Wallet من DB أو يقوم بإنشائهما."""
    user = db.query(User).filter(User.telegram_id == tg_user.id).first()
    if not user:
        user = User(
            telegram_id=tg_user.id,
            first_name=tg_user.first_name,
            username=tg_user.username,
        )
        db.add(user)
        db.flush()

    wallet = user.wallet
    if wallet is None:
        wallet = Wallet(user_id=user.id, balance_cents=0)
        db.add(wallet)
        db.flush()

    return user, wallet


def get_user_balance(user_id: int) -> int:
    """جلب رصيد المستخدم من wallets.balance_cents."""
    db: Session = SessionLocal()
    try:
        tg_user = type("TgUserProxy", (), {"id": user_id, "first_name": None, "username": None})
        _, wallet = _get_or_create_user_and_wallet(db, tg_user)
        db.commit()
        return wallet.balance_cents or 0
    except Exception as e:
        logger.exception("get_user_balance error: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


def add_user_points(user_id: int, delta: int) -> int:
    """إضافة/خصم نقاط من wallet.balance_cents."""
    db: Session = SessionLocal()
    try:
        tg_user = type("TgUserProxy", (), {"id": user_id, "first_name": None, "username": None})
        _, wallet = _get_or_create_user_and_wallet(db, tg_user)
        wallet.balance_cents = max(0, (wallet.balance_cents or 0) + delta)
        db.commit()
        return wallet.balance_cents
    except Exception as e:
        logger.exception("add_user_points error: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


def require_points(update: Update, needed_points: int) -> bool:
    """تحقق من وجود رصيد كافٍ."""
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
    """يتحقق من الرصيد ثم يخصم النقاط."""
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

# =============== المحفظة والأسعار ===============

def wallet_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    balance = get_user_balance(user.id)

    msg = (
        f"💳 *محفظتك في مرويات*\n\n"
        f"🔢 رصيدك الحالي: *{balance}* نقطة.\n\n"
        "لشحن المحفظة:\n"
        "1️⃣ اشترِ *كود شحن* من متجر مرويات في سلة.\n"
        "2️⃣ سيصلك رمز الشحن في رسالة من سلة.\n"
        "3️⃣ ادخل هنا واستخدم الأمر /redeem أو زر 🎟 شحن برمز من سلة.\n"
        "4️⃣ أرسل الكود، ولو كان صحيحًا وغير مستخدم ستُضاف النقاط إلى محفظتك.\n"
    )
    update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


def pricing_command(update: Update, context: CallbackContext) -> None:
    pricing_text = get_pricing_text()
    update.message.reply_text(
        pricing_text,
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

# =============== شحن برمز من سلة (redeem_codes) ===============

def redeem_command(update: Update, context: CallbackContext) -> int:
    """بدء عملية شحن المحفظة برمز من سلة."""
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


def redeem_code_logic(tg_user, raw_text: str):
    """
    يتحقق من الكود في جدول RedeemCode ويضيف النقاط إلى Wallet.
    """
    if not raw_text:
        return False, "⚠️ لم أستطع قراءة الكود، أرسله مرة أخرى."

    code_text = raw_text.strip().upper()

    prefixes = ["MRW-100-", "MRW-50-", "MRW-500-", "MRW-1100-", "MRW-"]
    for p in prefixes:
        if code_text.startswith(p):
            code_text = code_text[len(p):]
            break

    if not code_text:
        return False, "⚠️ الكود فارغ بعد التنظيف، تأكد من نسخه بشكل صحيح."

    db = SessionLocal()
    try:
        user, wallet = _get_or_create_user_and_wallet(db, tg_user)

        redeem = db.query(RedeemCode).filter(RedeemCode.code == code_text).first()

        if not redeem:
            return False, "❌ هذا الكود غير صحيح."

        if redeem.is_redeemed:
            return False, "⛔ تم استخدام هذا الكود من قبل."

        points = redeem.points or 0
        wallet.balance_cents += points

        redeem.is_redeemed = True
        redeem.redeemed_by_user_id = user.id
        redeem.redeemed_at = datetime.utcnow()

        db.commit()

        return True, (
            f"🎉 تم شحن *{points}* نقطة إلى محفظتك بنجاح.\n"
            f"🔢 رصيدك الحالي: {wallet.balance_cents} نقطة."
        )
    except Exception as e:
        db.rollback()
        logger.exception("Redeem code error: %s", e)
        return False, "⚠️ حدث خطأ أثناء معالجة الكود، حاول مرة أخرى لاحقاً."
    finally:
        db.close()


def handle_redeem_code(update: Update, context: CallbackContext) -> int:
    """يستقبل الكود من المستخدم ويشحن المحفظة."""
    user = update.effective_user
    text = (update.message.text or "").strip()

    success, message = redeem_code_logic(user, text)

    if success:
        update.message.reply_text(
            message,
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END
    else:
        update.message.reply_text(
            message,
            parse_mode="Markdown",
        )
        return STATE_REDEEM_CODE

# =============== /start ===============

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات للقصص.\n\n"
        "المميزات المتاحة حالياً:\n"
        "1️⃣ ✍️ كتابة قصة جديدة بالذكاء الاصطناعي — /write\n"
        "2️⃣ 📤 نشر قصة من كتابتك — /publish\n"
        "3️⃣ 🎬 إنتاج فيديو بالذكاء الاصطناعي — /video\n"
        "4️⃣ 📥 استعلام عن فيديو سابق — /video_status\n"
        "5️⃣ 🖼 إنشاء صورة بالذكاء الاصطناعي — /image\n"
        "6️⃣ 💰 عرض الأسعار والنقاط — /pricing\n"
        "7️⃣ 💳 عرض رصيد المحفظة — /wallet\n"
        "8️⃣ 🎟 شحن المحفظة برمز من سلة — /redeem\n\n"
        "اختر من الأزرار بالأسفل أو استخدم الأوامر.",
        reply_markup=MAIN_KEYBOARD,
    )

# ====================== القصص ======================

def write_command(update: Update, context: CallbackContext) -> int:
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
    genre_text = (update.message.text or "").strip()
    context.user_data["story_genre"] = genre_text

    update.message.reply_text(
        "رائع! الآن اكتب لي *فكرة القصة* في رسالة واحدة، مثلاً:\n"
        "• من هو البطل أو البطلة؟\n"
        "• أين تدور الأحداث؟\n"
        "• ما المشكلة أو اللغز الرئيسي؟\n\n"
        "كلما كانت فكرتك أوضح، كانت القصة أفضل 🌟",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return STATE_STORY_BRIEF


def generate_story_with_openai(brief: str, genre: str, username: str = "") -> str:
    if client is None:
        return "❌ إعداد خدمة الذكاء الاصطناعي غير مكتمل حالياً."

    user_prompt = (
        f"نوع القصة المطلوب: {genre}\n\n"
        f"هذه فكرة القصة من المستخدم (@{username}):\n\n"
        f"{brief}\n\n"
        "اكتب قصة كاملة وفق هذه الفكرة وهذا النوع."
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
        logger.exception("AI story error: %s", e)
        return "❌ حدث خطأ أثناء الاتصال بخدمة الذكاء الاصطناعي. حاول مرة أخرى لاحقاً."


def receive_story_brief(update: Update, context: CallbackContext) -> int:
    brief = (update.message.text or "").strip()
    genre = context.user_data.get("story_genre", "غير محدد")

    if not brief:
        update.message.reply_text("❗ لم أستطع قراءة وصف القصة، أعد كتابته من فضلك.")
        return STATE_STORY_BRIEF

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

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

# ====================== مراجعة / نشر قصة ======================

def review_story_with_openai(text: str, username: str = ""):
    if client is None:
        return {
            "approved": False,
            "word_count": len(text.split()),
            "title": "",
            "reasons": "إعداد خدمة الذكاء الاصطناعي غير مكتمل.",
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
        logger.exception("AI review error: %s", e)
        return {
            "approved": False,
            "word_count": len(text.split()),
            "title": "",
            "reasons": "حدث خطأ أثناء مراجعة القصة بالذكاء الاصطناعي.",
            "suggestions": "",
        }


def publish_command(update: Update, context: CallbackContext) -> int:
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
        "بعد الإرسال سأقوم بتحليل القصة بالذكاء الاصطناعي وإخبارك هل تم قبولها للنشر في 'قصص المجتمع'.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return STATE_PUBLISH_STORY


def handle_pdf_story(update: Update, context: CallbackContext) -> int:
    doc = update.message.document

    if not doc or doc.mime_type != "application/pdf":
        update.message.reply_text("❗ من فضلك أرسل ملف PDF صالح يحتوي على القصة.")
        return STATE_PUBLISH_STORY

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text("📥 تم استلام ملف PDF، جاري استخلاص النص وتحليله بالذكاء الاصطناعي...")

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
        update.message.reply_text("❌ حدث خطأ أثناء قراءة ملف الـPDF.")
        return ConversationHandler.END

    cleaned_text = full_text.strip()
    if not cleaned_text:
        update.message.reply_text("❌ لم أتمكن من استخراج أي نص من ملف الـPDF.")
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
                "⚠️ تم قبول القصة، لكن حدث خطأ أثناء نشرها في المجتمع.",
                reply_markup=MAIN_KEYBOARD,
            )
            return ConversationHandler.END
    else:
        update.message.reply_text(
            "✅ القصة مقبولة، لكن لم يتم ضبط COMMUNITY_CHAT_ID في الإعدادات.",
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
    text = (update.message.text or "").strip()

    if not text:
        update.message.reply_text("لم أستطع قراءة نص القصة، أعد الإرسال من فضلك.")
        return STATE_PUBLISH_STORY

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text("🔎 جاري تحليل قصتك والتأكد من جاهزيتها للنشر بالذكاء الاصطناعي...")

    review = review_story_with_openai(text, username=username)
    approved = bool(review.get("approved"))
    word_count = int(review.get("word_count") or len(text.split()))
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
        "حالياً النشر التلقائي للنصوص غير مفعّل.\n"
        "شكرًا لمشاركتك 🌟"
    )
    update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

    return ConversationHandler.END

# ====================== فيديو بالذكاء الاصطناعي ======================

def video_command(update: Update, context: CallbackContext) -> int:
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
        "• طفل يمشي في مكتبة قديمة.\n"
        "• لقطة سينمائية لجزيرة مهجورة وقت الغروب.\n\n"
        "بعد ذلك سأطلب منك تحديد مدة الفيديو بالثواني.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_VIDEO_IDEA


def refine_video_prompt_with_openai(idea: str, extra_info: str = "", username: str = ""):
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

        # نحاول أولاً نقرأه كـ JSON
        try:
            data = json.loads(raw)
            return data
        except json.JSONDecodeError:
            # لو ما التزم بالـ JSON نستخدم الرد كنص برومبت جاهز
            logger.warning("Video prompt is not valid JSON, using raw text as final prompt.")
            return {
                "status": "ok",
                "final_prompt": raw,
                "duration_seconds": 10,   # قيمة افتراضية معقولة
                "aspect_ratio": "16:9",
            }

    except Exception as e:
        logger.exception("OpenAI video prompt error: %s", e)
        return {"status": "error", "error": str(e)}


def _map_duration_to_runway(seconds: int) -> int:
    # القيم المدعومة داخلياً من خدمة الفيديو
    if seconds <= 5:
        return 4
    elif seconds <= 10:
        return 6
    else:
        return
