import os
import sqlite3
import asyncio
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CRITICAL: Create Flask app with CORRECT name ====================
application = Flask(__name__)  # THIS MUST BE 'application' for Gunicorn
app = application  # Alias for convenience

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")

# ==================== SIMPLE DATABASE ====================
def init_db():
    """Initialize database"""
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
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

init_db()

# ==================== DATABASE FUNCTIONS ====================
def get_user(telegram_id):
    """Get user by telegram ID"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = c.fetchone()
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'telegram_id': user[1],
            'username': user[2],
            'first_name': user[3],
            'phone_number': user[4],
            'balance': user[5]
        }
    return None

def create_user(telegram_id, username, first_name):
    """Create new user"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                  (telegram_id, username, first_name))
        conn.commit()
    except Exception as e:
        logger.error(f"Error creating user: {e}")
    finally:
        conn.close()

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    logger.info(f"Start from {user.first_name} (ID: {user.id})")
    
    # Create or get user
    db_user = get_user(user.id)
    if not db_user:
        create_user(user.id, user.username, user.first_name)
        db_user = get_user(user.id)
    
    # Create web app button
    keyboard = [[InlineKeyboardButton(
        "🎮 PLAY BINGO",
        web_app={"url": f"{APP_URL}/game?user={user.id}"}
    )]]
    
    await update.message.reply_text(
        f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
        f"💰 Balance: {db_user['balance']} ETB\n\n"
        f"Click the button below to play!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shared contact"""
    contact = update.message.contact
    user = update.effective_user
    
    if contact and contact.user_id == user.id:
        # Save phone number
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("UPDATE users SET phone_number = ? WHERE telegram_id = ?",
                  (contact.phone_number, user.id))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Phone number saved: {contact.phone_number}")
    else:
        await update.message.reply_text("❌ Please share your own contact")

# ==================== FIXED BOT SETUP with proper asyncio ====================
def run_bot():
    """Run bot in separate thread with proper event loop"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create application
        bot_app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        
        logger.info("Starting bot...")
        
        # Run the bot in this thread's event loop
        bot_app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        loop.close()

# Start bot in thread
if BOT_TOKEN:
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")
else:
    logger.error("BOT_TOKEN not set!")

# ==================== FLASK ROUTES ====================
@application.route('/')
def index():
    return render_template('index.html')

@application.route('/game')
def game():
    user_id = request.args.get('user', 'guest')
    balance = 1000
    
    if user_id != 'guest':
        user = get_user(int(user_id))
        if user:
            balance = user['balance']
    
    return render_template('index.html', user_id=user_id, balance=balance)

@application.route('/api/user/<int:telegram_id>')
def get_user_data(telegram_id):
    user = get_user(telegram_id)
    if user:
        return jsonify({
            'success': True,
            'balance': user['balance'],
            'phone': user['phone_number'] or ''
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot': 'running' if BOT_TOKEN else 'no token'
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)