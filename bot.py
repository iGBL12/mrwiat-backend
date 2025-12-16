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

# مفاتيح خدمة الفيديو بالذكاء الاصطناعي (Runway في الخلفية)
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

COMMUNITY_CHAT_URL = os.environ.get("COMMUNITY_CHAT_URL")
ARTICLES_CHAT_URL = os.environ.get("ARTICLES_CHAT_URL")

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
STORY_COST_POINTS = 5        # قصة نصية

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
STATE_ARTICLE_REVIEW = 20

# لوحة الأزرار الرئيسية
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["✍️ كتابة قصة بالذكاء الاصطناعي"],
        ["📤 نشر قصة من كتابتك", "📰 رفع مقال PDF"],
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
أنت خبير في صناعة برومبت احترافي لمولد فيديو يعمل بالذكاء الاصطناعي.

مهمتك:
1. استلام وصف لفكرة فيديو من المستخدم (غالباً بالعربية).
2. تقييم وضوح الفكرة.
3. إذا كانت الفكرة غير كافية، اطلب تفاصيل إضافية عن:
   - الشخصيات (العمر، الشكل، الملابس)
   - المكان (مدينة، غرفة، طبيعة، ليل/نهار)
   - أسلوب التصوير (سينمائي، لقطة ثابتة، حركة كاميرا...)
   - المزاج (غامض، احتفالي، حزين، مرعب، مرح...)
   - مدة الفيديو (مثلاً 5–10 ثوانٍ، 10–20 ثانية).

4. إذا كانت الفكرة كافية، أنشئ برومبت نهائي باللغة الإنجليزية، مفصل وواضح، وجاهز للإرسال إلى نموذج إنشاء الفيديو بالذكاء الاصطناعي.

✳️ مهم جداً:
- جميع الرسائل أو الأسئلة التي ستُعرض للمستخدم يجب أن تكون **باللغة العربية الفصحى فقط**.
- يمنع استخدام اللغة الإنجليزية في الأسئلة أو الشرح الموجّه للمستخدم.
- يُسمح باستخدام اللغة الإنجليزية فقط داخل `final_prompt` لأنه موجه لنموذج إنشاء الفيديو وليس للمستخدم.

أعد النتيجة دائماً في صيغة JSON فقط بهذا الشكل:

إذا كانت الفكرة غير واضحة بما يكفي:
{
  "status": "need_more",
  "questions": [
    "اكتب هنا سؤالاً بالعربية لطلب تفاصيل أكثر عن الشخصيات...",
    "اكتب هنا سؤالاً بالعربية لطلب تفاصيل عن المكان أو أسلوب التصوير..."
  ]
}

إذا كانت الفكرة واضحة ومكتملة:
{
  "status": "ok",
  "final_prompt": "English detailed prompt for AI video generator...",
  "duration_seconds": 10,
  "aspect_ratio": "16:9"
}

لا تخرج عن هذا الشكل أبداً، ولا تضف أي مفاتيح أو نصوص أخرى خارج هذا الـ JSON.
"""
ARTICLE_REVIEW_PROMPT = """
أنت مدقق محتوى محترف لمنصة عربية.

سيتم تزويدك بنص مقال كامل.
مهمتك التحقق مما يلي بدقة:

1. التأكد أن المقال:
- لا يتناول السياسة أو الأحزاب أو الحكومات.
- خالٍ من العنصرية أو خطاب الكراهية.
- لا يحتوي تحريضًا أو إساءة أو تمييزًا.
- لا يحتوي محتوى إباحي أو غير لائق.
- مناسب للنشر العام.

2. أعد النتيجة بصيغة JSON فقط وبدون أي شرح إضافي:

{
  "approved": true أو false,
  "violations": [
    "اذكر نوع المخالفة إن وجدت (سياسة / عنصرية / تحريض / محتوى غير لائق)"
  ],
  "summary": "ملخص قصير جداً عن سبب القبول أو الرفض"
}

❗ لا تُرجع أي نص خارج JSON.
"""

IMAGE_PROMPT_SYSTEM = """
أنت مهندس برومبت للصور (Image Prompt Engineer) تعمل مع نموذج صور متقدم.

مهمتك:
- استلام وصف صورة من المستخدم (غالباً بالعربية).
- تحويله إلى برومبت باللغة الإنجليزية، مفصل وواضح، يناسب نموذج صور مثل DALL·E / GPT-Image.
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
    """يرجع User + Wallet من DB أو يقوم بإنشائهما.
       المستخدم الجديد يحصل تلقائياً على 5 نقاط مجانية."""
    
    user_created = False
    wallet_created = False

    # --- إنشاء المستخدم إذا لم يكن موجوداً ---
    user = db.query(User).filter(User.telegram_id == tg_user.id).first()
    if not user:
        user = User(
            telegram_id=tg_user.id,
            first_name=tg_user.first_name,
            username=tg_user.username,
        )
        db.add(user)
        db.flush()
        user_created = True

    # --- إنشاء المحفظة إذا لم تكن موجودة ---
    wallet = user.wallet
    if wallet is None:
        wallet = Wallet(user_id=user.id, balance_cents=0)
        db.add(wallet)
        wallet_created = True

        # 🎁 مكافأة ترحيبية للمستخدم الجديد
        wallet.balance_cents = 5   # 5 نقاط مجانية

    # --- حفظ التغييرات ---
    if user_created or wallet_created:
        db.commit()

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
            "💳 اشترِ كود شحن من متجر *مرويات*:\n🔗 https://salla.sa/mrwiat\n\n"
            "ثم استخدم الأمر /redeem أو زر 🎟 شحن برمز من سلة لإضافة الرصيد.",
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
        "1️⃣ اشترِ *كود شحن* من متجر مرويات في سلة:\n"
        "🔗 https://salla.sa/mrwiat\n\n"
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
        "إذا لم تشترِ كودًا بعد، تفضل هنا:\n🔗 https://salla.sa/mrwiat\n\n"
        "🎟 جميل! أرسل الآن *رمز الشحن* الذي اشتريته من متجر سلة.\n\n"
        "مثال (الشكل فقط، ليس كودًا حقيقياً):\n"
        "`XYZ111`\n\n"
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

def build_article_caption(filename: str, username: str) -> str:
    title = filename.replace(".pdf", "").replace("مقال |", "").strip()
    return (
        f"📰 *{title}*\n"
        f"✍️ الكاتب: @{username}\n\n"
        "قسم: المقالات — منصة مرويات"
    )

def review_article_with_openai(text: str):
    if client is None:
        return {
            "approved": False,
            "violations": ["خدمة الذكاء الاصطناعي غير مفعّلة"],
            "summary": "لا يمكن فحص المقال حالياً"
        }

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": ARTICLE_REVIEW_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )

        raw = completion.choices[0].message.content.strip()
        return json.loads(raw)

    except Exception as e:
        logger.exception("Article review error: %s", e)
        return {
            "approved": False,
            "violations": ["خطأ تقني أثناء فحص المقال"],
            "summary": "حدث خطأ أثناء التحليل"
        }
def article_command(update: Update, context: CallbackContext) -> int:
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "📄 لفحص مقال PDF، تواصل معي في الخاص.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "📄 أرسل الآن *ملف PDF* للمقال.\n\n"
        "⚠️ شرط مهم:\n"
        "اسم الملف يجب أن يبدأ بـ:\n"
        "`مقال | اسم المقال`\n\n"
        "مثال:\n"
        "`مقال | أثر القراءة على التفكير.pdf`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return STATE_ARTICLE_REVIEW
def handle_article_pdf(update: Update, context: CallbackContext) -> int:
    doc = update.message.document

    # 1️⃣ تحقق من وجود ملف PDF
    if not doc or doc.mime_type != "application/pdf":
        update.message.reply_text(
            "❗ من فضلك أرسل ملف PDF صالح للمقال."
        )
        return STATE_ARTICLE_REVIEW

    filename = doc.file_name or ""

    # 2️⃣ تحقق من اسم الملف
    if not filename.startswith("مقال -"):
        update.message.reply_text(
            "❌ اسم الملف غير صحيح.\n\n"
            "يجب أن يبدأ اسم الملف بـ:\n"
            "`مقال - اسم المقال`\n\n"
            "مثال:\n"
            "`مقال - أثر القراءة على التفكير.pdf`"
,
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    user = update.effective_user
    username = user.username or user.first_name or "كاتب مرويات"

    update.message.reply_text(
        "🔍 تم استلام المقال.\n"
        "جاري قراءة الملف وفحص المحتوى للتأكد من خلوه من المخالفات..."
    )

    # 3️⃣ قراءة ملف PDF
    try:
        file = doc.get_file()
        bio = BytesIO()
        file.download(out=bio)
        bio.seek(0)

        reader = PyPDF2.PdfReader(bio)
        full_text = ""

        for page in reader.pages:
            full_text += (page.extract_text() or "") + "\n"

    except Exception as e:
        logger.exception("PDF article read error: %s", e)
        update.message.reply_text(
            "❌ حدث خطأ أثناء قراءة ملف الـ PDF."
        )
        return ConversationHandler.END

    text = full_text.strip()

    if not text:
        update.message.reply_text(
            "❌ لم أتمكن من استخراج أي نص من المقال."
        )
        return ConversationHandler.END

    # 4️⃣ حد أقصى للنص المرسل للذكاء الاصطناعي
    MAX_CHARS = 15000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    # 5️⃣ فحص المقال بالذكاء الاصطناعي
    review = review_article_with_openai(text)

    approved = bool(review.get("approved"))
    violations = review.get("violations", [])
    summary = review.get("summary", "")

    # 6️⃣ في حال وجود مخالفات
    if not approved:
        msg = (
            "🚫 *تم رفض المقال*\n\n"
            "⚠️ تم اكتشاف المخالفات التالية:\n"
        )

        for v in violations:
            msg += f"- {v}\n"

        if summary:
            msg += f"\n📝 ملاحظات:\n{summary}"

        update.message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    # 7️⃣ المقال سليم ➜ نشره في قروب المقالات
    articles_chat = normalize_chat_target(ARTICLES_CHAT_URL)

    if not articles_chat:
        update.message.reply_text(
            "✅ المقال سليم، لكن لم يتم ضبط مكان نشر المقالات في الإعدادات.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    try:
        title = filename.replace(".pdf", "").replace("مقال -", "").strip()

        caption = (
            f"📰 *{title}*\n"
            f"✍️ الكاتب: @{username}\n\n"
            "قسم: المقالات — منصة مرويات"
        )

        context.bot.send_document(
            chat_id=articles_chat,
            document=doc.file_id,
            caption=caption,
            parse_mode="Markdown",
        )

        update.message.reply_text(
            "🎉 *تم فحص المقال بنجاح ونشره في قسم المقالات.*\n"
            "شكرًا لمساهمتك ✨",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )

    except Exception as e:
        logger.exception("Error sending article to articles group: %s", e)
        update.message.reply_text(
            "⚠️ المقال سليم، لكن حدث خطأ أثناء نشره في القروب.",
            reply_markup=MAIN_KEYBOARD,
        )

    return ConversationHandler.END

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

def normalize_chat_target(chat_url):
    if not chat_url:
        return None

    chat_url = chat_url.strip()

    if chat_url.startswith("https://t.me/"):
        return "@" + chat_url.split("https://t.me/")[-1]

    if chat_url.startswith("t.me/"):
        return "@" + chat_url.split("t.me/")[-1]

    if chat_url.startswith("@"):
        return chat_url

    return chat_url


# =============== /start ===============

def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    db = SessionLocal()
    u, w = _get_or_create_user_and_wallet(db, user)
    welcome_bonus_msg = ""
    if w.balance_cents == 5:
        welcome_bonus_msg = "🎁 لقد حصلت على *5 نقاط مجانية* هدية ترحيبية!"



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
        return "❌ خدمة الذكاء الاصطناعي غير مفعّلة حالياً، حاول لاحقاً."

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
            "reasons": "خدمة الذكاء الاصطناعي غير مفعّلة حالياً.",
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
        "بعد الإرسال سأقوم بتحليل القصة وإخبارك هل تم قبولها للنشر في 'قصص المجتمع'.",
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

    # ❌ غير مقبولة
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

        update.message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    # ✅ مقبولة
    update.message.reply_text(
        f"✅ تم تحليل قصتك من ملف الـPDF.\n"
        f"📊 عدد الكلمات التقريبي: *{word_count}* كلمة.\n"
        "📣 النتيجة: *صالحة للنشر في قسم قصص المجتمع*.\n\n"
        "🚀 سيتم الآن نشر ملف الـPDF في مجتمع مرويات باسمك.",
        parse_mode="Markdown",
    )

    community_chat = normalize_chat_target(COMMUNITY_CHAT_URL)

    if not community_chat:
        update.message.reply_text(
            "✅ القصة مقبولة، لكن لم يتم ضبط COMMUNITY_CHAT_URL في الإعدادات.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    try:
        caption = (
            f"📖 *{title}*\n"
            f"✍️ من القارئ: @{username}\n\n"
            "قسم: قصص المجتمع — منصة مرويات."
        )

        context.bot.send_document(
            chat_id=community_chat,
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

    update.message.reply_text("🔎 جاري تحليل قصتك والتأكد من جاهزيتها للنشر...")

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

# ====================== فيديو ======================

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
        return {"status": "error", "error": "No AI client configured."}

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

        try:
            data = json.loads(raw)
        except Exception as e:
            logger.error(f"JSON ERROR: {e}\nRAW RESPONSE:\n{raw}")
            return {"status": "error", "error": "JSON parse failed"}

        # تطبيع للنسخ القديمة إن رجعت بصيغة مختلفة
        if "status" not in data:
            clarity = data.get("clarity")
            if clarity and clarity != "clear":
                questions = data.get("missing_details") or []
                if not questions and data.get("request_for_more_info"):
                    questions = [data["request_for_more_info"]]
                return {"status": "need_more", "questions": questions}
            elif clarity == "clear" and "final_prompt" in data:
                data["status"] = "ok"
                return data
            else:
                return {"status": "error", "error": "Unexpected JSON schema"}

        return data

    except Exception as e:
        logger.exception("AI video prompt error: %s", e)
        return {"status": "error", "error": "حدث خطأ أثناء تحليل فكرة الفيديو."}


def _map_duration_to_runway(seconds: int) -> int:
    if seconds <= 5:
        return 4
    elif seconds <= 10:
        return 6
    else:
        return 8


def create_runway_video_generation(prompt: str, duration_seconds: int = 10, aspect_ratio: str = "1280:720"):
    if not RUNWAY_API_KEY:
        return {"ok": False, "error": "Video AI service key is not set."}

    mapped_duration = _map_duration_to_runway(duration_seconds)

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": RUNWAY_API_VERSION,
    }

    payload = {
        "model": RUNWAY_MODEL,
        "promptText": prompt,
        "ratio": aspect_ratio,
        "audio": False,
        "duration": mapped_duration,
    }

    try:
        resp = requests.post(RUNWAY_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            return {"ok": False, "error": f"Video AI service error: {resp.status_code} {resp.text}"}
        data = resp.json()
        return {"ok": True, "data": data}
    except Exception as e:
        logger.exception("Video AI API error: %s", e)
        return {"ok": False, "error": "فشل الاتصال بخدمة إنشاء الفيديو بالذكاء الاصطناعي."}


def get_runway_task_detail(task_id: str):
    if not RUNWAY_API_KEY:
        return {"ok": False, "error": "Video AI service key is not set."}

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
                "error": f"Video task detail error: {resp.status_code} {resp.text}",
                "status_code": resp.status_code,
            }
        return {"ok": True, "data": resp.json()}
    except Exception as e:
        logger.exception("Video task detail error: %s", e)
        return {"ok": False, "error": "فشل جلب حالة مهمة إنشاء الفيديو."}


def wait_for_runway_task(task_id: str, max_wait: int = 60, poll_interval: int = 6):
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

        time.sleep(poll_interval)

    return {
        "ok": False,
        "status": str(last_data.get("status")) if isinstance(last_data, dict) else "UNKNOWN",
        "data": last_data,
        "error": "TIMEOUT",
    }


def extract_runway_video_url(task_data: dict):
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
    runway_resp = create_runway_video_generation(
        prompt=final_prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
    )

    if not runway_resp.get("ok"):
        update.message.reply_text(
            f"⚠️ تم تجهيز برومبت الفيديو، لكن حدث خطأ عند الإرسال إلى خدمة إنشاء الفيديو بالذكاء الاصطناعي:\n{runway_resp.get('error')}",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    data = runway_resp.get("data", {})
    gen_id = data.get("id", "غير معروف")

    update.message.reply_text(
        "🚀 تم إرسال طلب إنشاء الفيديو إلى خدمة الذكاء الاصطناعي بنجاح.\n"
        f"🆔 رقم الطلب: `{gen_id}`",
        parse_mode="Markdown",
    )

    update.message.reply_text("⏳ جاري متابعة حالة مهمة إنشاء الفيديو، انتظر قليلاً...")

    wait_result = wait_for_runway_task(gen_id, max_wait=60, poll_interval=6)

    if not wait_result.get("ok"):
        status = wait_result.get("status")
        if status:
            msg = (
                f"ℹ️ حالة المهمة الحالية في خدمة إنشاء الفيديو: *{status}*.\n"
                "قد تستمر المعالجة هناك، يمكنك متابعة التقدم من لوحة الخدمة باستخدام رقم الطلب."
            )
            update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        else:
            update.message.reply_text(
                "⚠️ لم أستطع التأكد من انتهاء مهمة إنشاء الفيديو الآن.",
                reply_markup=MAIN_KEYBOARD,
            )
        return

    task_data = wait_result.get("data") or {}
    video_url = extract_runway_video_url(task_data)

    if video_url:
        try:
            update.message.reply_text("🎉 تم إنشاء الفيديو بالذكاء الاصطناعي! سأرسله لك الآن...")
            context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_url,
                caption="🎬 الفيديو الناتج من خدمة إنشاء الفيديو بالذكاء الاصطناعي.",
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
            "✅ المهمة انتهت بنجاح في خدمة إنشاء الفيديو، لكن لم أستطع العثور على رابط الفيديو بشكل واضح.\n"
            "هذا الردّ القادم من خدمة الذكاء الاصطناعي:\n"
            f"```json\n{pretty}\n```",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )


def handle_video_idea(update: Update, context: CallbackContext) -> int:
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
            "📤 الآن سأرسل الطلب إلى خدمة إنشاء الفيديو بالذكاء الاصطناعي ومتابعة حالته...",
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
        "📤 الآن سأرسل الطلب إلى خدمة إنشاء الفيديو بالذكاء الاصطناعي ومتابعة حالته...",
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
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "📥 للاستعلام عن حالة فيديو سبق إنشاؤه بالذكاء الاصطناعي، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /video_status هناك.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    update.message.reply_text(
        "📥 أرسل الآن *رقم الطلب* الذي حصلت عليه عند إنشاء الفيديو (على شكل UUID):\n"
        "`103d6a74-a651-4a6d-ada5-df8c640117ec` كمثال.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_VIDEO_STATUS_ID


def handle_video_status(update: Update, context: CallbackContext) -> int:
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
            f"⚠️ حدث خطأ أثناء جلب حالة الطلب من خدمة إنشاء الفيديو:\n{result.get('error')}",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    data = result.get("data", {})
    status = str(data.get("status", "غير معروف")).upper()

    base_msg = (
        f"ℹ️ حالة مهمة الفيديو في خدمة الذكاء الاصطناعي:\n\n"
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
                    caption="🎬 الفيديو الناتج من خدمة إنشاء الفيديو بالذكاء الاصطناعي لهذا الطلب.",
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
                "هذا الردّ القادم من خدمة إنشاء الفيديو:\n"
                f"```json\n{pretty}\n```",
                parse_mode="Markdown",
                reply_markup=MAIN_KEYBOARD,
            )
    else:
        update.message.reply_text(
            base_msg
            + "\n\nقد تكون المهمة ما زالت قيد التنفيذ أو فشلت.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )

    return ConversationHandler.END

# ====================== صور ======================

def image_command(update: Update, context: CallbackContext) -> int:
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
        "سأحوّل وصفك إلى برومبت احترافي وأنتج لك صورة بالذكاء الاصطناعي.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_IMAGE_PROMPT


def generate_image_prompt_with_openai(description: str) -> str:
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
        logger.exception("AI image prompt error: %s", e)
        return ""


def handle_image_prompt(update: Update, context: CallbackContext) -> int:
    desc = (update.message.text or "").strip()
    if not desc:
        update.message.reply_text("❗ لم أستطع قراءة وصف الصورة، أعد كتابته من فضلك.")
        return STATE_IMAGE_PROMPT

    if not require_and_deduct(update, IMAGE_COST_POINTS):
        return ConversationHandler.END

    update.message.reply_text("🎨 جاري تحويل وصفك إلى برومبت احترافي وإنشاء الصورة بالذكاء الاصطناعي...")

    refined_prompt = generate_image_prompt_with_openai(desc)
    if not refined_prompt:
        update.message.reply_text(
            "❌ حدث خطأ أثناء تجهيز برومبت الصورة. حاول مرة أخرى.",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    if client is None:
        update.message.reply_text(
            "❌ خدمة إنشاء الصور بالذكاء الاصطناعي غير مفعّلة حالياً.",
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
            raise RuntimeError("No URL returned from image service")

        image_url = img_resp.data[0].url

    except Exception as e:
        logger.exception("AI image generation error: %s", e)
        update.message.reply_text(
            f"❌ حدث خطأ أثناء توليد الصورة بخدمة الذكاء الاصطناعي:\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    caption = (
        "🖼 هذه هي الصورة الناتجة عن وصفك بالذكاء الاصطناعي.\n"
        "إذا أعجبتك، يمكنك حفظها أو استخدامها كغلاف لقصة في مرويات."
    )
    update.message.reply_photo(photo=image_url, caption=caption, reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# =============== /cancel ===============

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
    dp.add_handler(
    MessageHandler(
        Filters.regex("^📰 رفع مقال PDF$"),
        article_command,
        )
    )


    # ===================== أوامر أساسية =====================
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("pricing", pricing_command))
    dp.add_handler(CommandHandler("wallet", wallet_command))
    dp.add_handler(CommandHandler("myid", myid_command))
    dp.add_handler(CommandHandler("id", myid_command))

    # ===================== أزرار المحفظة والأسعار =====================
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

    # ===================== كتابة قصة =====================
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

    # ===================== نشر قصة =====================
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

    # ===================== فيديو =====================
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

    # ===================== حالة فيديو =====================
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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(video_status_conv)

    # ===================== صور =====================
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

    # ===================== شحن برمز من سلة =====================
    redeem_conv = ConversationHandler(
        entry_points=[
            CommandHandler("redeem", redeem_command),
            MessageHandler(
                Filters.regex("^(🎟 )?شحن برمز من سلة$"),
                redeem_command,
            ),
        ],
        states={
            STATE_REDEEM_CODE: [
                MessageHandler(Filters.text & ~Filters.command, handle_redeem_code)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(redeem_conv)

    # ===================== 📰 فحص ونشر المقالات (NEW) =====================
    article_conv = ConversationHandler(
        entry_points=[
            CommandHandler("article", article_command),
        ],
        states={
            STATE_ARTICLE_REVIEW: [
                MessageHandler(Filters.document.pdf, handle_article_pdf)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(article_conv)

    # ===================== تشغيل البوت =====================
    updater.start_polling()
    updater.idle()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # أوامر أساسية
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("pricing", pricing_command))
    dp.add_handler(CommandHandler("wallet", wallet_command))
    dp.add_handler(CommandHandler("myid", myid_command))
    dp.add_handler(CommandHandler("id", myid_command))

    # أزرار المحفظة والأسعار
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

    # كتابة قصة
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

    article_conv = ConversationHandler(
    entry_points=[CommandHandler("article", article_command)],
    states={
        STATE_ARTICLE_REVIEW: [
            MessageHandler(Filters.document.pdf, handle_article_pdf)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)



    # نشر قصة
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

    # فيديو
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

    # حالة فيديو
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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(video_status_conv)

    # صورة
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

    # شحن برمز من سلة
    redeem_conv = ConversationHandler(
        entry_points=[
            CommandHandler("redeem", redeem_command),
            MessageHandler(
                Filters.regex("^(🎟 )?شحن برمز من سلة$"),
                redeem_command,
            ),
        ],
        states={
            STATE_REDEEM_CODE: [
                MessageHandler(Filters.text & ~Filters.command, handle_redeem_code)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(redeem_conv)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
