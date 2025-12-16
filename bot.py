# ===================== Imports =====================
import os
import logging
import json
import time
from io import BytesIO
from textwrap import wrap
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

from sqlalchemy.orm import Session
from database import Base, engine, SessionLocal
from models import User, Wallet, RedeemCode

# ===================== Config =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

COMMUNITY_CHAT_URL = os.environ.get("COMMUNITY_CHAT_URL")
ARTICLES_CHAT_URL = os.environ.get("ARTICLES_CHAT_URL")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

Base.metadata.create_all(bind=engine)

# ===================== States =====================
(
    STATE_STORY_GENRE,
    STATE_STORY_BRIEF,
    STATE_PUBLISH_STORY,
    STATE_VIDEO_IDEA,
    STATE_VIDEO_CLARIFY,
    STATE_IMAGE_PROMPT,
    STATE_VIDEO_DURATION,
    STATE_VIDEO_STATUS_ID,
    STATE_REDEEM_CODE,
    STATE_ARTICLE_REVIEW,
) = (1,2,3,4,5,6,7,8,9,20)

# ===================== Keyboards =====================
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

# ===================== Helpers =====================
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

# ===================== Article Review =====================
ARTICLE_REVIEW_PROMPT = """
أنت مدقق محتوى محترف.
تحقق أن المقال لا يحتوي سياسة أو عنصرية أو تحريض أو محتوى غير لائق.

أعد النتيجة JSON فقط:
{
  "approved": true أو false,
  "violations": ["..."],
  "summary": "سبب مختصر"
}
"""

def review_article_with_openai(text: str):
    if not client:
        return {"approved": False, "violations": ["AI غير مفعّل"], "summary": ""}
    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": ARTICLE_REVIEW_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        logger.exception(e)
        return {"approved": False, "violations": ["خطأ تقني"], "summary": ""}

# ===================== Article Commands =====================
def article_command(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "📄 أرسل ملف PDF للمقال.\n\n"
        "⚠️ يجب أن يبدأ الاسم بـ:\n"
        "`مقال - اسم المقال.pdf`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return STATE_ARTICLE_REVIEW

def handle_article_pdf(update: Update, context: CallbackContext) -> int:
    doc = update.message.document

    if not doc or doc.mime_type != "application/pdf":
        update.message.reply_text("❗ أرسل ملف PDF صالح.")
        return STATE_ARTICLE_REVIEW

    filename = (doc.file_name or "").strip()
    if not filename.lower().startswith("مقال -"):
        update.message.reply_text(
            "❌ اسم الملف غير صحيح.\n"
            "مثال صحيح:\n`مقال - الأكل الصحي.pdf`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    update.message.reply_text("🔍 جاري فحص المقال...")

    try:
        file = doc.get_file()
        bio = BytesIO()
        file.download(out=bio)
        bio.seek(0)
        reader = PyPDF2.PdfReader(bio)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        logger.exception(e)
        update.message.reply_text("❌ خطأ أثناء قراءة الملف.")
        return ConversationHandler.END

    review = review_article_with_openai(text[:15000])

    if not review.get("approved"):
        msg = "🚫 تم رفض المقال:\n"
        for v in review.get("violations", []):
            msg += f"- {v}\n"
        update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    chat = normalize_chat_target(ARTICLES_CHAT_URL)
    if not chat:
        update.message.reply_text("⚠️ لم يتم ضبط قروب المقالات.")
        return ConversationHandler.END

    title = filename.replace(".pdf", "").replace("مقال -", "").strip()
    context.bot.send_document(
        chat_id=chat,
        document=doc.file_id,
        caption=f"📰 *{title}*\nقسم المقالات — مرويات",
        parse_mode="Markdown",
    )

    update.message.reply_text(
        "✅ تم نشر المقال بنجاح 🎉",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END

# ===================== Start =====================
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات",
        reply_markup=MAIN_KEYBOARD,
    )

# ===================== Main =====================
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    article_conv = ConversationHandler(
        entry_points=[
            CommandHandler("article", article_command),
            MessageHandler(Filters.regex("^📰 رفع مقال PDF$"), article_command),
        ],
        states={
            STATE_ARTICLE_REVIEW: [
                MessageHandler(Filters.document.pdf, handle_article_pdf)
            ]
        },
        fallbacks=[CommandHandler("cancel", start)],
    )
    dp.add_handler(article_conv)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
