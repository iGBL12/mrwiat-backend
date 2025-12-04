# bot.py
import os
import logging
from textwrap import wrap

from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    Filters,
    CallbackContext,
)

from openai import OpenAI

# =============== الإعدادات العامة ===============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Story generation will fail.")

client = OpenAI(api_key=OPENAI_API_KEY)

# حالات المحادثة
STATE_STORY_BRIEF = 1      # لوصف القصة المراد توليدها بالذكاء الاصطناعي
STATE_PUBLISH_STORY = 2    # لنص القصة التي يريد المستخدم نشرها


# =============== /start ===============
def start(update: Update, context: CallbackContext) -> None:
    """رسالة ترحيب بسيطة مع توضيح الأوامر المتاحة."""
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات للقصص.\n\n"
        "المميزات المتاحة حالياً:\n"
        "1️⃣ ✍️ كتابة قصة جديدة بالذكاء الاصطناعي:\n"
        "   استخدم الأمر /write ثم أرسل فكرة القصة.\n\n"
        "2️⃣ 📤 نشر قصة من كتابتك:\n"
        "   استخدم الأمر /publish ثم أرسل نص القصة كاملة (على الأقل 1000 كلمة)."
    )


# =============== /write — بدء إنشاء القصة بالذكاء الاصطناعي ===============
def write_command(update: Update, context: CallbackContext) -> int:
    """يبدأ محادثة إنشاء قصة جديدة باستخدام OpenAI."""

    if update.effective_chat.type != "private":
        update.message.reply_text(
            "✍️ لإنشاء قصة جديدة، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /write هناك."
        )
        return ConversationHandler.END

    update.message.reply_text(
        "✨ أهلاً بك في مختبر مرويات لكتابة القصص.\n\n"
        "اكتب لي الآن *فكرة القصة* في رسالة واحدة، مثلاً:\n"
        "• نوع القصة (غموض، رعب، خيال علمي، رومانسية...)\n"
        "• بطل أو بطلة القصة\n"
        "• المكان والزمن\n"
        "• أي تفاصيل مهمة تريد إضافتها\n\n"
        "بعدها سأقوم بكتابة قصة كاملة بناءً على فكرتك.",
        parse_mode="Markdown",
    )

    return STATE_STORY_BRIEF


def generate_story_with_openai(brief: str, username: str = "") -> str:
    """يستدعي OpenAI لكتابة قصة عربية بناءً على الوصف."""

    if not OPENAI_API_KEY:
        return "❌ لا يوجد إعداد لمفتاح OpenAI حالياً (OPENAI_API_KEY)."

    system_prompt = (
        "أنت كاتب قصص عربي محترف تعمل لصالح منصة 'مرويات'. "
        "اكتب قصة أدبية مشوقة باللغة العربية الفصحى السهلة، مع حوارات جذابة، "
        "وبناء واضح للبداية والعقدة والنهاية. "
        "حافظ على طول القصة تقريباً بين 800 إلى 1300 كلمة. "
        "تجنّب المواضيع الحساسة أو المخالفة للسياسات."
    )

    user_prompt = (
        f"هذه فكرة القصة من المستخدم (@{username}):\n\n"
        f"{brief}\n\n"
        "اكتب قصة كاملة وفق هذه الفكرة. "
        "قسّم القصة إلى فقرات قصيرة لسهولة القراءة داخل تيليجرام."
    )

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
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
    """يستقبل وصف القصة، يستدعي OpenAI، ويرسل القصة الناتجة للمستخدم."""
    brief = (update.message.text or "").strip()

    if not brief:
        update.message.reply_text("❗ لم أستطع قراءة وصف القصة، أعد كتابته من فضلك.")
        return STATE_STORY_BRIEF

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text(
        "⏳ جميل! جاري الآن كتابة القصة بناءً على فكرتك...\n"
        "قد يستغرق ذلك بضع ثوانٍ.",
    )

    story_text = generate_story_with_openai(brief, username=username)

    if story_text.startswith("❌"):
        update.message.reply_text(story_text)
        return ConversationHandler.END

    MAX_LEN = 3500
    chunks = wrap(story_text, MAX_LEN, break_long_words=False, replace_whitespace=False)

    update.message.reply_text("✅ تم إنشاء القصة! إليك النص:")

    for i, chunk in enumerate(chunks, start=1):
        header = f"الجزء {i}:\n\n" if len(chunks) > 1 else ""
        update.message.reply_text(header + chunk)

    update.message.reply_text(
        "🎉 انتهينا! إذا أعجبتك القصة يمكنك حفظها أو مشاركتها.\n"
        "لإنشاء قصة جديدة استخدم الأمر /write مرة أخرى."
    )

    return ConversationHandler.END


# =============== /publish — نشر قصة كتبها المستخدم ===============
def publish_command(update: Update, context: CallbackContext) -> int:
    """يبدأ محادثة استقبال قصة من المستخدم."""
    if update.effective_chat.type != "private":
        update.message.reply_text(
            "📤 لنشر قصة من كتابتك، تواصل معي في الخاص.\n"
            "افتح البوت واضغط /publish هناك."
        )
        return ConversationHandler.END

    update.message.reply_text(
        "📤 جميل! سنقوم الآن باستقبال قصتك.\n\n"
        "أرسل نص القصة كاملة في *رسالة واحدة*.\n"
        "▪️ الحد الأدنى: 1000 كلمة.\n"
        "▪️ يمكنك نسخ القصة من ملف وورد ولصقها هنا.\n\n"
        "بعد الإرسال سأخبرك هل القصة جاهزة للنشر أم تحتاج تطوير.",
        parse_mode="Markdown",
    )

    return STATE_PUBLISH_STORY


def receive_publish_story(update: Update, context: CallbackContext) -> int:
    """يستقبل نص القصة من المستخدم ويتحقق من عدد الكلمات."""
    text = (update.message.text or "").strip()

    if not text:
        update.message.reply_text("لم أستطع قراءة نص القصة، أعد الإرسال من فضلك.")
        return STATE_PUBLISH_STORY

    words = [w for w in text.split() if w.strip()]
    word_count = len(words)

    if word_count < 1000:
        update.message.reply_text(
            f"🔎 عدد كلمات قصتك الآن هو *{word_count}* كلمة فقط.\n"
            f"الحد الأدنى للنشر في مرويات هو *1000* كلمة.\n\n"
            "حاول إضافة:\n"
            "• وصف للمكان\n"
            "• تفاصيل أكثر عن الشخصيات\n"
            "• حوارات بين الشخصيات\n\n"
            "ثم أعد إرسال القصة كاملة في رسالة واحدة.",
            parse_mode="Markdown",
        )
        return STATE_PUBLISH_STORY

    # حفظ مؤقت في user_data (لاحقاً يمكن إرسالها لباك إند أو PDF)
    context.user_data["last_published_story"] = text
    context.user_data["last_published_words"] = word_count

    update.message.reply_text(
        "✅ تم استلام قصتك بنجاح!\n\n"
        f"عدد الكلمات: *{word_count}* كلمة.\n\n"
        "سيتم لاحقاً ربط البوت بنظام مرويات لمراجعة القصة "
        "وتحويلها إلى PDF ونشرها في قسم 'قصص المجتمع' باسمك.\n"
        "شكرًا لمشاركتك 🌟",
        parse_mode="Markdown",
    )

    return ConversationHandler.END


# =============== /cancel — إلغاء أي محادثة ===============
def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "تم إلغاء العملية. يمكنك البدء من جديد بالأوامر:\n"
        "/write أو /publish."
    )
    return ConversationHandler.END


# =============== main ===============
def main() -> None:
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    # محادثة كتابة قصة بالذكاء الاصطناعي
    story_conv = ConversationHandler(
        entry_points=[CommandHandler("write", write_command)],
        states={
            STATE_STORY_BRIEF: [
                MessageHandler(Filters.text & ~Filters.command, receive_story_brief)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(story_conv)

    # محادثة نشر قصة من كتابة المستخدم
    publish_conv = ConversationHandler(
        entry_points=[CommandHandler("publish", publish_command)],
        states={
            STATE_PUBLISH_STORY: [
                MessageHandler(
                    Filters.text & ~Filters.command, receive_publish_story
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(publish_conv)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
