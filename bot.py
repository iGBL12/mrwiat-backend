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
from sqlalchemy.orm import Session
from database import Base, engine, SessionLocal
from models import User, Wallet, RedeemCode

import re

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

# تأكد من إنشاء الجداول (User, Wallet, RedeemCode, ...)
Base.metadata.create_all(bind=engine)

# ======== أسعار النقاط =========

IMAGE_COST_POINTS = 10        # إنشاء صورة
STORY_COST_POINTS = 20        # قصة نصية

def get_video_cost_points(duration_seconds: int) -> int:
    if duration_seconds <= 10:
        return 40
    elif duration_seconds <= 15:
        return 55
    elif duration_seconds <= 20:
        return 70
    else:
        return 100  # احتياط لو زادت المدة مستقبلاً

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

# لوحة نوع القصة
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
...
هدفك النهائي هو كتابة قصة ممتعة بجودة عالية تجعل القارئ يشعر بأنه يشاهد فيلمًا قصيرًا مكتوبًا بإتقان.
"""

REVIEW_PROMPT = """
أنت محرر رئيسي في منصة "مرويات" للقصص العربية.
...
"""

VIDEO_PROMPT_SYSTEM = """
أنت خبير في صناعة برومبت احترافي لمولد فيديو مثل Runway Gen-2.
...
"""

IMAGE_PROMPT_SYSTEM = """
أنت مهندس برومبت للصور (Image Prompt Engineer) تعمل مع نموذج صور متقدم.
...
"""

# =============== دوال عامة للمستخدم والمحفظة ===============

def get_user_id(update: Update) -> int:
    return update.effective_user.id


def myid_command(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        f"🔢 Telegram ID الخاص بك هو:\n`{user.id}`",
        parse_mode="Markdown",
    )


def get_user_balance(user_id: int) -> int:
    """
    جلب رصيد المستخدم من wallets.balance_cents
    مع إنشاء user + wallet إذا لم يكونا موجودين.
    """
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            user = User(telegram_id=user_id)
            db.add(user)
            db.flush()

        wallet = user.wallet
        if wallet is None:
            wallet = Wallet(user_id=user.id, balance_cents=0)
            db.add(wallet)
            db.commit()
            db.refresh(user)

        return wallet.balance_cents or 0
    except Exception as e:
        logger.exception("get_user_balance error: %s", e)
        return 0
    finally:
        db.close()


def add_user_points(user_id: int, delta: int) -> int:
    """
    إضافة/خصم نقاط من wallet.balance_cents في DB.
    يرجع الرصيد الجديد.
    """
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            user = User(telegram_id=user_id)
            db.add(user)
            db.flush()

        wallet = user.wallet
        if wallet is None:
            wallet = Wallet(user_id=user.id, balance_cents=0)
            db.add(wallet)

        wallet.balance_cents = max(0, (wallet.balance_cents or 0) + delta)

        db.commit()
        db.refresh(wallet)
        return wallet.balance_cents
    except Exception as e:
        logger.exception("add_user_points error: %s", e)
        db.rollback()
        return 0
    finally:
        db.close()


def require_points(update: Update, needed_points: int) -> bool:
    """
    يتحقق من أن رصيد المستخدم كافٍ.
    لو لا، يرسل له رسالة يطلب منه شحن المحفظة.
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
    يتحقق أن الرصيد كافٍ ثم يخصم النقاط من المحفظة.
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

# =============== أكواد الشحن (redeem_codes) ===============

def redeem_start(update, context):
    update.message.reply_text(
        "جميل! 👌\n"
        "🧾 أرسل الآن *رمز الشحن* الذي اشتريته من متجر سلة.\n\n"
        "مثال (الشكل فقط، ليس كود حقيقي):\n"
        "`MRW-100-XYZ111`\n\n"
        "تأكد من نسخه كما هو تمامًا بدون مسافات إضافية.",
        parse_mode="Markdown",
    )


def redeem_code_logic(tg_user, raw_text: str):
    """
    منطق شحن الكود:
    - ينظف النص
    - يبحث في جدول RedeemCode
    - إن كان صحيحاً وغير مستخدم: يضيف النقاط إلى Wallet.balance_cents
    يرجع (success: bool, message: str)
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
        # احصل/أنشئ User + Wallet
        user = db.query(User).filter(User.telegram_id == tg_user.id).first()
        if not user:
            user = User(
                telegram_id=tg_user.id,
                first_name=tg_user.first_name,
                username=tg_user.username,
            )
            db.add(user)
            db.flush()

            wallet = Wallet(user_id=user.id, balance_cents=0)
            db.add(wallet)
            db.commit()
            db.refresh(user)
        else:
            wallet = user.wallet
            if wallet is None:
                wallet = Wallet(user_id=user.id, balance_cents=0)
                db.add(wallet)
                db.commit()
                db.refresh(user)

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


def receive_redeem(update, context):
    """
    (اختياري) فلتر لأي رسالة تشبه الكود، يمكن ربطه إن أردت.
    حالياً غير مستخدم في الـ handlers.
    """
    user = update.effective_user
    text = (update.message.text or "").strip()
    norm = text.upper()
    if not re.fullmatch(r"[A-Z0-9\-]{6,20}", norm):
        return
    success, message = redeem_code_logic(user, text)
    update.message.reply_text(message, parse_mode="Markdown")


def wallet_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    balance = get_user_balance(user.id)

    msg = (
        f"💳 *محفظتك في مرويات*\n\n"
        f"🔢 رصيدك الحالي: *{balance}* نقطة.\n\n"
        "لشحن المحفظة:\n"
        "1️⃣ اشترِ *كود شحن* من متجر مرويات في سلة (حسب الباقة).\n"
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


def redeem_command(update: Update, context: CallbackContext) -> int:
    """
    بدء عملية شحن المحفظة برمز من سلة (محادثة).
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
    يستقبل كود الشحن، يتحقق منه في جدول redeem_codes،
    ويضيف النقاط إلى wallet.balance_cents.
    """
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
        "3️⃣ 🎬 إنتاج فيديو بالذكاء الاصطناعي (Runway) — /video\n"
        "4️⃣ 📥 استعلام عن فيديو سابق — /video_status\n"
        "5️⃣ 🖼 إنشاء صورة بالذكاء الاصطناعي — /image\n"
        "6️⃣ 💰 عرض الأسعار والنقاط — /pricing\n"
        "7️⃣ 💳 عرض رصيد المحفظة — /wallet\n"
        "8️⃣ 🎟 شحن المحفظة برمز من سلة — /redeem\n\n"
        "اختر من الأزرار بالأسفل أو استخدم الأوامر.",
        reply_markup=MAIN_KEYBOARD,
    )

# ================= باقي دوال القصص / النشر / الفيديو / الصور =================
# (نفس ما كان عندك مع استخدام require_and_deduct عند الاستهلاك)

# ... هنا تبقي جميع الدوال:
# write_command, handle_story_genre, generate_story_with_openai,
# receive_story_brief, review_story_with_openai,
# publish_command, handle_pdf_story, receive_publish_story,
# video_command, refine_video_prompt_with_openai, _map_duration_to_runway,
# create_runway_video_generation, get_runway_task_detail, wait_for_runway_task,
# extract_runway_video_url, send_runway_request_and_reply,
# handle_video_idea, handle_video_duration, handle_video_clarify,
# video_status_command, handle_video_status,
# image_command, generate_image_prompt_with_openai, handle_image_prompt,
# cancel
# (لم أغيّر فيها شيئاً غير أنها تعتمد على require_and_deduct/get_user_balance)

# =============== main ===============

def main() -> None:
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

    # محادثة كتابة قصة
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

    # محادثة نشر قصة
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

    # محادثة فيديو
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

    # محادثة استعلام عن فيديو
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

    # محادثة صورة
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

    # محادثة شحن برمز من سلة
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
