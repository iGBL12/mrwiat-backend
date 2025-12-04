import os
import asyncio

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.error import Forbidden

# ========= الإعدادات =========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://mrwiat.com/app/wallet.html")

# عدّل هذه بحسب حساباتك
MRWIAT_BOT_USERNAME = "MRWIAT_BOT"          # بدون @
MRWIAT_GROUP_LINK = "https://t.me/MRWIAT01"            # رابط القروب
MRWIAT_LIBRARY_LINK = "https://t.me/MRWIAT01/4"          # رابط قناة المكتبة (إذا أنشأتها)


# ========= /start =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(
                text="💰 محفظتي",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "أهلاً بك في محفظة مرويات 💰\nاضغط على الزر لفتح المحفظة داخل تيليجرام.",
        reply_markup=reply_markup,
    )


# ========= ترحيب بالعضو الجديد =========
async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يُستدعى عندما يدخل عضو جديد إلى القروب.
    - يرسل له رسالة خاصة (إن كان يسمح بذلك).
    - يمكن أن يرسل رسالة ترحيب في القروب (اختياري).
    """
    if not update.message or not update.message.new_chat_members:
        return

    for member in update.message.new_chat_members:
        # نتجنب البوتات
        if member.is_bot:
            continue

        user_id = member.id
        first_name = member.first_name or ""

        # ===== رسالة خاصة (DM) =====
        dm_text = f"""👋 أهلاً {first_name} في مجتمع مرويات!

أنا بوت مرويات، أساعدك في:

📚 1) قراءة قصص وروايات مرويات بصيغة PDF
   - مكتبة القصص الرسمية (قصص حصرية ومجانية)
   - كل قصة مصممة على شكل PDF صور لتقليل السرقة

✍️ 2) مشاركة قصصك أنت:
   - أرسل لي قصتك وسأقوم بفحص الأخطاء الإملائية
   - أعطيك تقييم للقصة وملاحظات لتحسينها
   - إذا كانت مناسبة أحولها إلى ملف PDF وأنشرها باسمك في قسم "قصص المجتمع"

💰 3) محفظة مرويات:
   - رصيد تستخدمه لقراءة القصص الحصرية وميزات أخرى
   - افتح المحفظة من الأمر /start أو من زر "محفظتي"

⭐ 4) اشتراك Basic (قريباً):
   - نشر عدد غير محدود من القصص
   - الوصول إلى قصص حصرية
   - مزايا إضافية داخل المحفظة

روابط مهمة:
- مجموعة مرويات: {MRWIAT_GROUP_LINK}
- قناة المكتبة: {MRWIAT_LIBRARY_LINK}

للبدء استخدم الأمر:
/start
"""

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=dm_text,
            )
        except Forbidden:
            # المستخدم لم يفتح البوت في الخاص أو حاذفه
            # نتجاهل الخطأ بهدوء
            pass

        # ===== (اختياري) رسالة ترحيب داخل القروب =====
        chat_id = update.message.chat_id
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"👋 أهلاً بـ {member.mention_html()} في مجتمع مرويات!",
            parse_mode="HTML",
        )


# ========= main =========
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment variables")

    application = Application.builder().token(BOT_TOKEN).build()

    # أوامر
    application.add_handler(CommandHandler("start", start))

    # ترحيب بالأعضاء الجدد في القروب
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            greet_new_member,
        )
    )

    # تشغيل البوت
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()
