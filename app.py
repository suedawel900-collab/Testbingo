import os
import sqlite3
import logging
import asyncio
from flask import Flask, request, jsonify, render_template
from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
application = Flask(__name__)
app = application

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID", "0")
APP_URL = os.environ.get("RAILWAY_STATIC_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "mkbingo_secret")

logger.info("Starting MK Bingo Bot")

# ==================== DATABASE ====================
def init_db():
    os.makedirs("database", exist_ok=True)

    conn = sqlite3.connect("database/bingo.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        phone_number TEXT,
        balance INTEGER DEFAULT 1000
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ==================== DB FUNCTIONS ====================
def get_user(telegram_id):
    conn = sqlite3.connect("database/bingo.db")
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    user = c.fetchone()

    conn.close()

    if user:
        return {
            "telegram_id": user[1],
            "username": user[2],
            "first_name": user[3],
            "phone_number": user[4],
            "balance": user[5]
        }

    return None


def create_user(tid, username, name):
    conn = sqlite3.connect("database/bingo.db")
    c = conn.cursor()

    c.execute(
        "INSERT OR IGNORE INTO users (telegram_id,username,first_name) VALUES (?,?,?)",
        (tid, username, name)
    )

    conn.commit()
    conn.close()


def update_phone(tid, phone):
    conn = sqlite3.connect("database/bingo.db")
    c = conn.cursor()

    c.execute(
        "UPDATE users SET phone_number=? WHERE telegram_id=?",
        (phone, tid)
    )

    conn.commit()
    conn.close()

# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    db_user = get_user(user.id)

    if not db_user:
        create_user(user.id, user.username, user.first_name)
        db_user = get_user(user.id)

    if not db_user["phone_number"]:

        keyboard = [[KeyboardButton(
            "📱 Share Phone Number",
            request_contact=True
        )]]

        markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await update.message.reply_text(
            "📱 Please share your phone number",
            reply_markup=markup
        )
        return

    keyboard = [[InlineKeyboardButton(
        "🎮 PLAY BINGO",
        web_app={"url": f"https://{APP_URL}/game?user={user.id}"}
    )]]

    await update.message.reply_text(
        f"🎰 Welcome {user.first_name}\n"
        f"💰 Balance: {db_user['balance']} ETB",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):

    contact = update.message.contact
    user = update.effective_user

    if contact.user_id == user.id:

        update_phone(user.id, contact.phone_number)

        keyboard = [[InlineKeyboardButton(
            "🎮 PLAY BINGO",
            web_app={"url": f"https://{APP_URL}/game?user={user.id}"}
        )]]

        await update.message.reply_text(
            "✅ Phone saved",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.message.reply_text("❌ Send your own contact")


async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("Use /start")

# ==================== BOT SETUP ====================

bot_app = Application.builder().token(BOT_TOKEN).build()

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.CONTACT, contact))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))

# ==================== WEBHOOK ROUTE ====================

@application.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
async def telegram_webhook():

    data = request.get_json()

    update = Update.de_json(data, bot_app.bot)

    await bot_app.process_update(update)

    return "ok"

# ==================== WEBSITE ====================

@application.route("/")
def home():
    return render_template("index.html")

@application.route("/game")
def game():

    uid = request.args.get("user")

    balance = 1000
    phone = ""

    if uid:
        user = get_user(int(uid))

        if user:
            balance = user["balance"]
            phone = user["phone_number"]

    return render_template(
        "index.html",
        user_id=uid,
        balance=balance,
        phone=phone
    )

# ==================== API ====================

@application.route("/api/user/<int:uid>")
def api_user(uid):

    user = get_user(uid)

    if user:

        return jsonify({
            "success": True,
            "balance": user["balance"],
            "phone": user["phone_number"]
        })

    return jsonify({"success": False})

# ==================== HEALTH ====================

@application.route("/health")
def health():

    return jsonify({
        "status": "ok"
    })

# ==================== START ====================

async def set_webhook():

    url = f"https://{APP_URL}/webhook/{WEBHOOK_SECRET}"

    await bot_app.bot.set_webhook(url)

    logger.info(f"Webhook set: {url}")

asyncio.get_event_loop().run_until_complete(set_webhook())

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    application.run(
        host="0.0.0.0",
        port=port
    )