# bot.py
import os
import logging
import json
from io import BytesIO
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
import PyPDF2

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

# القروب / القناة التي سيتم النشر فيها عند الموافقة على القصة
COMMUNITY_CHAT_ID = os.environ.get("COMMUNITY_CHAT_ID")  # مثال: -1001234567890

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Story generation / review will fail.")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

# =============== ثوابت الحالات في المحادثة ===============

STATE_STORY_GENRE = 1      # اختيار نوع القصة
STATE_STORY_BRIEF = 2      # وصف فكرة القصة
STATE_PUBLISH_STORY = 3    # نص القصة أو PDF الذي يريد المستخدم نشره

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

# =============== SYSTEM PROMPT لكتابة القصص ===============

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

# =============== SYSTEM PROMPT لمراجعة القصص (نص أو PDF) ===============

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

# =============== /start ===============

def start(update: Update, context: CallbackContext) -> None:
    """رسالة ترحيب بسيطة مع توضيح الأوامر المتاحة + الأزرار."""
    update.message.reply_text(
        "👋 أهلاً بك في بوت مرويات للقصص.\n\n"
        "المميزات المتاحة حالياً:\n"
        "1️⃣ ✍️ كتابة قصة جديدة بالذكاء الاصطناعي.\n"
        "2️⃣ 📤 نشر قصة من كتابتك (نص أو ملف PDF، حد أدنى ~1000 كلمة).\n\n"
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

# =============== دالة استدعاء OpenAI لكتابة قصة ===============

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

# =============== دالة مراجعة قصة (نص) عبر OpenAI ===============

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

        # محاولة قراءة JSON
        data = json.loads(raw)
        # تأكيد الحقول الأساسية
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

# =============== /publish — نشر قصة كتبها المستخدم (نص أو PDF) ===============

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

    # يمكن تقصير النص إذا كان ضخماً جداً لتقليل التكلفة
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

    # القصة مقبولة للنشر
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

    # محادثة نشر قصة من كتابة المستخدم (نص أو PDF)
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
                # استقبال ملفات PDF
                MessageHandler(Filters.document.pdf, handle_pdf_story),
                # استقبال نص عادي
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

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
