import os
import json
import sqlite3
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TimedOut, NetworkError

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create Flask app
flask_app = Flask(__name__)
app = flask_app  # For Gunicorn

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting application with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"ADMIN_ID: {ADMIN_ID}")
logger.info(f"APP_URL: {APP_URL}")

# ==================== DATABASE ====================
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
                  balance INTEGER DEFAULT 1000,
                  games_played INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  total_deposits INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Game settings
    c.execute('''CREATE TABLE IF NOT EXISTS game_settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_type TEXT DEFAULT 'full house',
                  card_price INTEGER DEFAULT 10,
                  prize_pool INTEGER DEFAULT 2000)''')
    
    # Insert default settings
    c.execute("SELECT COUNT(*) FROM game_settings")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO game_settings (game_type, card_price, prize_pool) VALUES (?, ?, ?)",
                  ('full house', 10, 2000))
    
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
            'balance': user[4],
            'games_played': user[5],
            'wins': user[6],
            'total_deposits': user[7],
            'created_at': user[8]
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
        logger.info(f"User created: {username} ({telegram_id})")
    except Exception as e:
        logger.error(f"Error creating user: {e}")
    finally:
        conn.close()

def update_balance(telegram_id, amount, operation='add'):
    """Update user balance"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    if operation == 'add':
        c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
    else:
        c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (amount, telegram_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
    new_balance = c.fetchone()[0]
    conn.close()
    return new_balance

def get_game_settings():
    """Get game settings"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT game_type, card_price, prize_pool FROM game_settings LIMIT 1")
    settings = c.fetchone()
    conn.close()
    
    if settings:
        return {
            'game_type': settings[0],
            'card_price': settings[1],
            'prize_pool': settings[2]
        }
    return {'game_type': 'full house', 'card_price': 10, 'prize_pool': 2000}

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        telegram_id = user.id
        
        logger.info(f"Start command from {user.first_name} (@{user.username})")
        
        # Create or get user
        db_user = get_user(telegram_id)
        if not db_user:
            create_user(telegram_id, user.username, user.first_name)
            db_user = get_user(telegram_id)
        
        # Create Web App button
        keyboard = [
            [InlineKeyboardButton(
                "🎮 PLAY BINGO",
                web_app={"url": f"{APP_URL}/game?user={telegram_id}"}
            )],
            [InlineKeyboardButton("💰 BALANCE", callback_data="balance")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
            f"💰 Balance: {db_user['balance']} ETB\n\n"
            f"Click PLAY BINGO to start!",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "balance":
        user = get_user(query.from_user.id)
        if user:
            await query.edit_message_text(f"💰 Your balance: {user['balance']} ETB")

# ==================== BOT SETUP ====================
def run_bot():
    """Run bot in a separate thread"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    try:
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_callback))
        
        logger.info("Starting bot polling...")
        
        # Start polling (this blocks)
        application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True,
            close_loop=False
        )
        
    except Exception as e:
        logger.error(f"Bot error: {e}")

# Start bot in thread only if token exists
if BOT_TOKEN:
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")
else:
    logger.error("BOT_TOKEN not set!")

# ==================== FLASK ROUTES ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/game')
def game():
    user_id = request.args.get('user', 'guest')
    if user_id != 'guest':
        user = get_user(int(user_id))
        if user:
            return render_template('index.html', user_id=user_id, balance=user['balance'])
    return render_template('index.html', user_id='guest', balance=1000)

@app.route('/api/user/<int:telegram_id>')
def get_user_data(telegram_id):
    user = get_user(telegram_id)
    if user:
        return jsonify({'success': True, 'balance': user['balance']})
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.route('/api/game/settings')
def game_settings_api():
    settings = get_game_settings()
    return jsonify({'success': True, **settings})

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'bot': 'running' if BOT_TOKEN else 'no token'
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)