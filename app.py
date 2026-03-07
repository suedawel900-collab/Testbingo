import os
import json
import sqlite3
import threading
import asyncio
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# CRITICAL FIX: Create Flask app with BOTH names
flask_app = Flask(__name__)  # This creates the Flask app
application = flask_app       # THIS is what Gunicorn is looking for
app = flask_app              # Keep 'app' for backward compatibility

# Configuration from environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting application with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}... and ADMIN_ID: {ADMIN_ID}")

# Initialize bot
bot = None
if BOT_TOKEN:
    try:
        bot = Bot(token=BOT_TOKEN)
        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")

# ==================== DATABASE SETUP ====================
def init_db():
    """Initialize database tables"""
    # Ensure database directory exists
    os.makedirs('database', exist_ok=True)
    
    conn = None
    try:
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
        
        # Transactions table
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      tx_id TEXT UNIQUE,
                      amount INTEGER DEFAULT 0,
                      status TEXT DEFAULT 'pending',
                      receipt_url TEXT,
                      approved_by INTEGER,
                      approved_at TIMESTAMP,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (user_id) REFERENCES users(id))''')
        
        # Game history table
        c.execute('''CREATE TABLE IF NOT EXISTS game_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      game_type TEXT,
                      cards_bought INTEGER,
                      amount_paid INTEGER,
                      won BOOLEAN DEFAULT FALSE,
                      prize INTEGER DEFAULT 0,
                      played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (user_id) REFERENCES users(id))''')
        
        # Game settings table
        c.execute('''CREATE TABLE IF NOT EXISTS game_settings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      game_type TEXT DEFAULT 'full house',
                      card_price INTEGER DEFAULT 10,
                      prize_pool INTEGER DEFAULT 2000,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Insert default settings if not exists
        c.execute("SELECT COUNT(*) FROM game_settings")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO game_settings (game_type, card_price, prize_pool) VALUES (?, ?, ?)",
                      ('full house', 10, 2000))
            logger.info("Default game settings inserted")
        
        conn.commit()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

# Initialize database
init_db()

# ==================== DATABASE HELPER FUNCTIONS ====================
def get_user(telegram_id):
    """Get user by telegram ID"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = c.fetchone()
        
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
    except Exception as e:
        logger.error(f"Error getting user {telegram_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def create_user(telegram_id, username, first_name):
    """Create new user"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                  (telegram_id, username, first_name))
        conn.commit()
        logger.info(f"New user created: {username} ({telegram_id})")
        return True
    except Exception as e:
        logger.error(f"Error creating user {telegram_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def update_balance(telegram_id, amount, operation='add'):
    """Update user balance"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        
        if operation == 'add':
            c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
        else:
            c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (amount, telegram_id))
        
        conn.commit()
        
        # Get new balance
        c.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
        new_balance = c.fetchone()[0]
        return new_balance
    except Exception as e:
        logger.error(f"Error updating balance for {telegram_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_game_settings():
    """Get current game settings"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("SELECT game_type, card_price, prize_pool FROM game_settings ORDER BY updated_at DESC LIMIT 1")
        settings = c.fetchone()
        
        if settings:
            return {
                'game_type': settings[0],
                'card_price': settings[1],
                'prize_pool': settings[2]
            }
        return {'game_type': 'full house', 'card_price': 10, 'prize_pool': 2000}
    except Exception as e:
        logger.error(f"Error getting game settings: {e}")
        return {'game_type': 'full house', 'card_price': 10, 'prize_pool': 2000}
    finally:
        if conn:
            conn.close()

# ==================== SIMPLE BOT HANDLERS ====================
# Just a minimal bot to confirm it works
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        telegram_id = user.id
        
        # Check if user exists
        db_user = get_user(telegram_id)
        if not db_user:
            create_user(telegram_id, user.username, user.first_name)
            db_user = get_user(telegram_id)
        
        # Create Web App button
        keyboard = [
            [InlineKeyboardButton(
                "🎮 PLAY BINGO",
                web_app={"url": f"{APP_URL}/game?user={telegram_id}"}
            )]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"🎰 Welcome to MK BINGO, {user.first_name}!\n💰 Balance: {db_user['balance']} ETB"
        
        await update.message.reply_text(message, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in start handler: {e}")

# Setup bot only if token exists
if bot:
    def setup_bot():
        """Setup bot application"""
        try:
            application_bot = Application.builder().token(BOT_TOKEN).build()
            application_bot.add_handler(CommandHandler("start", start))
            logger.info("Bot handlers registered successfully")
            return application_bot
        except Exception as e:
            logger.error(f"Error setting up bot: {e}")
            return None

    def run_bot():
        """Run bot in separate thread"""
        try:
            application_bot = setup_bot()
            if application_bot:
                logger.info("Starting bot polling...")
                application_bot.run_polling()
            else:
                logger.error("Failed to setup bot")
        except Exception as e:
            logger.error(f"Error running bot: {e}")

    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")
else:
    logger.warning("Bot not started - no valid token")

# ==================== FLASK ROUTES ====================
# IMPORTANT: Use @application.route for all routes
@application.route('/')
def index():
    """Main page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return "Error loading page. Check that templates/index.html exists.", 500

@application.route('/game')
def game():
    """Serve game page"""
    try:
        user_id = request.args.get('user', 'guest')
        if user_id != 'guest':
            user = get_user(int(user_id))
            if user:
                return render_template('index.html', 
                                     user_id=user_id,
                                     balance=user['balance'],
                                     username=user['first_name'])
        return render_template('index.html', user_id='guest')
    except Exception as e:
        logger.error(f"Error in game route: {e}")
        return "Error loading game", 500

@application.route('/api/user/<int:telegram_id>')
def get_user_data(telegram_id):
    """Get user data for game"""
    try:
        user = get_user(telegram_id)
        if user:
            return jsonify({
                'success': True,
                'balance': user['balance'],
                'username': user['first_name']
            })
        return jsonify({'success': False, 'error': 'User not found'}), 404
    except Exception as e:
        logger.error(f"Error getting user data: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

@application.route('/api/game/settings')
def game_settings():
    """Get current game settings"""
    try:
        settings = get_game_settings()
        return jsonify({
            'success': True,
            'game_type': settings['game_type'],
            'card_price': settings['card_price'],
            'prize_pool': settings['prize_pool']
        })
    except Exception as e:
        logger.error(f"Error getting game settings: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

@application.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'bot_configured': bot is not None,
        'database': 'connected'
    })

# ==================== MAIN ENTRY POINT ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    application.run(host='0.0.0.0', port=port, debug=False)