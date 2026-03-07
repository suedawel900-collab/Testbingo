import os
import sqlite3
import logging
import multiprocessing
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Flask App Setup ====================
application = Flask(__name__)
app = application

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")

# ==================== Database ====================
def init_db():
    os.makedirs('database', exist_ok=True)
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
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

def get_user(telegram_id):
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

def update_user_phone(telegram_id, phone_number):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET phone_number = ? WHERE telegram_id = ?",
                  (phone_number, telegram_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating phone: {e}")
        return False
    finally:
        conn.close()

# ==================== Bot Process ====================
def run_bot_process():
    """Run bot in a separate process"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN in process")
        return
    
    logger.info(f"Bot process started with PID: {os.getpid()}")
    
    try:
        # Create application
        bot_app = Application.builder().token(BOT_TOKEN).build()
        
        # Define handlers inside the process
        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            logger.info(f"Start from {user.first_name}")
            
            # Create or get user
            db_user = get_user(user.id)
            if not db_user:
                create_user(user.id, user.username, user.first_name)
                db_user = get_user(user.id)
            
            # Check if phone number is needed
            if not db_user['phone_number']:
                contact_keyboard = [
                    [KeyboardButton("📱 Share Phone Number", request_contact=True)],
                    [KeyboardButton("❌ Skip")]
                ]
                reply_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
                
                await update.message.reply_text(
                    "📱 Please share your phone number:",
                    reply_markup=reply_markup
                )
                return
            
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
            contact = update.message.contact
            user = update.effective_user
            
            if contact and contact.user_id == user.id:
                if update_user_phone(user.id, contact.phone_number):
                    await update.message.reply_text(f"✅ Phone number saved!")
                    
                    db_user = get_user(user.id)
                    keyboard = [[InlineKeyboardButton(
                        "🎮 PLAY BINGO",
                        web_app={"url": f"{APP_URL}/game?user={user.id}"}
                    )]]
                    
                    await update.message.reply_text(
                        f"🎰 You can now play!",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await update.message.reply_text("❌ Error saving phone number")
            else:
                await update.message.reply_text("❌ Please share your own contact")

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("Please use /start to begin")

        # Add handlers
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Bot handlers registered, starting polling...")
        
        # Run polling (this blocks)
        bot_app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Bot process error: {e}")
        time.sleep(5)  # Wait before restarting

# ==================== Start Bot Process ====================
bot_process = None

def start_bot():
    """Start the bot in a separate process"""
    global bot_process
    if bot_process and bot_process.is_alive():
        logger.info("Bot process already running")
        return
    
    bot_process = multiprocessing.Process(target=run_bot_process, daemon=True)
    bot_process.start()
    logger.info(f"Bot process started with PID: {bot_process.pid}")

# Start bot if token exists
if BOT_TOKEN:
    start_bot()
else:
    logger.error("BOT_TOKEN not set!")

# ==================== Flask Routes ====================
@application.route('/')
def index():
    return render_template('index.html')

@application.route('/game')
def game():
    user_id = request.args.get('user', 'guest')
    balance = 1000
    phone = ''
    
    if user_id != 'guest':
        user = get_user(int(user_id))
        if user:
            balance = user['balance']
            phone = user['phone_number'] or ''
    
    return render_template('index.html', user_id=user_id, balance=balance, phone=phone)

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
        'bot_process': bot_process.is_alive() if bot_process else False,
        'pid': bot_process.pid if bot_process else None
    })

@application.route('/bot-status')
def bot_status():
    """Check if bot is running"""
    if bot_process and bot_process.is_alive():
        return jsonify({'status': 'running', 'pid': bot_process.pid})
    else:
        # Try to restart
        if BOT_TOKEN:
            start_bot()
            return jsonify({'status': 'restarting'})
        return jsonify({'status': 'no token'})

# ==================== Main ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)