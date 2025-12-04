# bot.py
import os
import logging
from textwrap import wrap

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

# =============== الإعدادات العامة ===============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
# نستخدم gpt-4.1-mini افتراضياً، ويمكن تغييره من المتغيرات
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Story generation will fail.")
    client = None
else:
    # ✅ استخدام عميل OpenAI الجديد بدون أي معاملات إضافية
    client = OpenAI(api_key=OPENAI_API_KEY)

# =============== ثوابت الحالات في المحادثة ===============

STATE_STORY_GENRE = 1      # اختيار نوع القصة
STATE_STORY_BRIEF = 2      # وصف فكرة القصة
STATE_PUBLISH_STORY = 3    # نص القصة التي يريد المستخدم نشرها

# لوحة الأزرار الرئيسية
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["✍️ كتابة قصة بالذكاء الاصطناعي"],
        ["📤 نشر قصة من كتابتك"],
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

# =============== SYSTEM PROMPT المتخصص لمرويات ===============

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

# =============== /start ===============

def start(update: Update, context: CallbackContext) -> None:
    """رسالة ترحيب بسيطة مع توضيح الأوامر المتاحة + الأزرار."""
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات للقصص.\n\n"
        "المميزات المتاحة حالياً:\n"
        "1️⃣ ✍️ كتابة قصة جديدة بالذكاء الاصطناعي.\n"
        "2️⃣ 📤 نشر قصة من كتابتك (حد أدنى 1000 كلمة).\n\n"
        "اختر من الأزرار بالأسفل أو استخدم الأوامر:\n"
        "/write أو /publish.",
        reply_markup=MAIN_KEYBOARD,
    )

# =============== /write — خطوة 1: اختيار نوع القصة ===============

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

    # نخزن نوع القصة كما هو
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

# =============== دالة استدعاء OpenAI مع النوع + الفكرة ===============

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
    """يستقبل وصف القصة، يستدعي OpenAI، ويرسل القصة الناتجة للمستخدم."""
    brief = (update.message.text or "").strip()
    genre = context.user_data.get("story_genre", "غير محدد")

    if not brief:
        update.message.reply_text("❗ لم أستطع قراءة وصف القصة، أعد كتابته من فضلك.")
        return STATE_STORY_BRIEF

    user = update.effective_user
    username = user.username or user.first_name or "قارئ مرويات"

    update.message.reply_text(
        f"⏳ جميل! سأكتب الآن قصة من نوع: {genre}\n"
        "بناءً على فكرتك... قد يستغرق ذلك بضع ثوانٍ.",
    )

    story_text = generate_story_with_openai(brief, genre=genre, username=username)

    if story_text.startswith("❌"):
        update.message.reply_text(story_text, reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    # تقسيم القصة على عدة رسائل حتى لا نتجاوز حد تيليجرام
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

# =============== /publish — نشر قصة كتبها المستخدم ===============

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
        "أرسل نص القصة كاملة في *رسالة واحدة*.\n"
        "▪️ الحد الأدنى: 1000 كلمة.\n"
        "▪️ يمكنك نسخ القصة من ملف وورد ولصقها هنا.\n\n"
        "بعد الإرسال سأخبرك هل القصة جاهزة للنشر أم تحتاج تطوير.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
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

    context.user_data["last_published_story"] = text
    context.user_data["last_published_words"] = word_count

    update.message.reply_text(
        "✅ تم استلام قصتك بنجاح!\n\n"
        f"عدد الكلمات: *{word_count}* كلمة.\n\n"
        "سيتم لاحقاً ربط البوت بنظام مرويات لمراجعة القصة "
        "وتحويلها إلى PDF ونشرها في قسم 'قصص المجتمع' باسمك.\n"
        "شكرًا لمشاركتك 🌟",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END

# =============== /cancel — إلغاء أي محادثة ===============

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "تم إلغاء العملية. يمكنك البدء من جديد بالأزرار أو بالأوامر:\n"
        "/write أو /publish.",
        reply_markup=MAIN_KEYBOARD,
    )
    return ConversationHandler.END

# =============== main ===============

def main() -> None:
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # /start
    dp.add_handler(CommandHandler("start", start))

    # محادثة كتابة قصة بالذكاء الاصطناعي
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

    # محادثة نشر قصة من كتابة المستخدم
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
                MessageHandler(
                    Filters.text & ~Filters.command,
                    receive_publish_story,
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
