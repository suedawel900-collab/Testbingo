import os
import sqlite3
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CRITICAL FIX: Create Flask app with CORRECT name ====================
application = Flask(__name__)  # THIS MUST BE NAMED 'application' for Gunicorn
app = application  # Alias for backward compatibility

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")

# ==================== SIMPLE DATABASE ====================
def init_db():
    os.makedirs('database', exist_ok=True)
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  first_name TEXT,
                  phone_number TEXT,
                  balance INTEGER DEFAULT 1000)''')
    
    # Game sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS game_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT UNIQUE,
                  total_cards_sold INTEGER DEFAULT 0,
                  total_players INTEGER DEFAULT 0,
                  status TEXT DEFAULT 'waiting')''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# ==================== SIMPLE BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    logger.info(f"Start from {user.first_name}")
    
    # Create web app button
    keyboard = [[InlineKeyboardButton(
        "🎮 PLAY BINGO",
        web_app={"url": f"{APP_URL}/game?user={user.id}"}
    )]]
    
    await update.message.reply_text(
        f"🎰 Welcome to MK BINGO!\nClick below to play:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shared contact"""
    contact = update.message.contact
    if contact:
        logger.info(f"Got phone: {contact.phone_number}")

# ==================== BOT SETUP ====================
def run_bot():
    """Run bot in separate thread"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    try:
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        
        logger.info("Starting bot...")
        bot_app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Bot error: {e}")

# Start bot thread
if BOT_TOKEN:
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("Bot thread started")

# ==================== FLASK ROUTES ====================
@application.route('/')
def index():
    return render_template('index.html')

@application.route('/game')
def game():
    user_id = request.args.get('user', 'guest')
    return render_template('index.html', user_id=user_id, balance=1000)

@application.route('/health')
def health():
    return jsonify({'status': 'ok', 'bot': bool(BOT_TOKEN)})

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)