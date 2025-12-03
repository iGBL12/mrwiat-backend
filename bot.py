import os
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")  # نأخذ التوكن من المتغيرات
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://mrwiat.com/app/wallet.html")


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


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in environment variables")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    # نستخدم event loop يدويًا لأننا على Python 3.12
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None,  # مهم على Render/ويندوز
    )


if __name__ == "__main__":
    main()
