import os
import json
import sqlite3
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.error import TimedOut, NetworkError

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create Flask app with multiple names for compatibility
flask_app = Flask(__name__)
application = flask_app  # For Gunicorn
app = flask_app          # For backward compatibility

# Configuration from environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

logger.info(f"Starting application with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"ADMIN_ID: {ADMIN_ID}")
logger.info(f"APP_URL: {APP_URL}")

# ==================== DATABASE SETUP ====================
def init_db():
    """Initialize database tables"""
    os.makedirs('database', exist_ok=True)
    
    conn = sqlite3.connect('database/bingo.db', check_same_thread=False)
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
    conn.close()
    logger.info("Database initialized successfully")

# Initialize database
init_db()

# ==================== DATABASE HELPER FUNCTIONS ====================
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

# ==================== TELEGRAM BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        telegram_id = user.id
        logger.info(f"Start command from user {telegram_id} (@{user.username})")
        
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
            [InlineKeyboardButton("💰 BALANCE", callback_data="balance")],
            [InlineKeyboardButton("📊 STATS", callback_data="stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"🎰 *Welcome to MK BINGO, {user.first_name}!*\n\n"
            f"💰 Your Balance: *{db_user['balance']} ETB*\n\n"
            f"Click the button below to start playing!"
        )
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        try:
            await update.message.reply_text("❌ An error occurred. Please try again later.")
        except:
            pass

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    logger.info(f"Button callback from user {user.id}: {data}")
    
    if data == "balance":
        db_user = get_user(user.id)
        if db_user:
            await query.edit_message_text(
                f"💰 *Your Balance*\n\n"
                f"Available: *{db_user['balance']} ETB*",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("User not found. Please use /start")
    
    elif data == "stats":
        db_user = get_user(user.id)
        if db_user:
            stats = (
                f"📊 *Your Stats*\n\n"
                f"💰 Balance: *{db_user['balance']} ETB*\n"
                f"🎮 Games Played: *{db_user['games_played']}*\n"
                f"🏆 Total Wins: *{db_user['wins']} ETB*\n"
                f"💳 Total Deposits: *{db_user['total_deposits']} ETB*"
            )
            await query.edit_message_text(stats, parse_mode='Markdown')
        else:
            await query.edit_message_text("User not found. Please use /start")

# ==================== BOT SETUP ====================
def run_bot():
    """Run bot in a separate thread with proper error handling"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Bot cannot start.")
        return
    
    max_retries = 5
    retry_delay = 10  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to start bot (attempt {attempt + 1}/{max_retries})...")
            
            # Create application
            bot_app = Application.builder().token(BOT_TOKEN).build()
            
            # Add handlers
            bot_app.add_handler(CommandHandler("start", start))
            bot_app.add_handler(CallbackQueryHandler(button_callback))
            
            logger.info("Bot handlers registered. Starting polling...")
            
            # Start polling
            bot_app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                timeout=30
            )
            
            # If we get here, polling is running
            logger.info("Bot is now polling for updates")
            break
            
        except (TimedOut, NetworkError) as e:
            logger.error(f"Network error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Bot failed to start.")
        
        except Exception as e:
            logger.error(f"Unexpected error starting bot: {e}")
            break

# Start bot in background thread
if BOT_TOKEN:
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")
else:
    logger.error("BOT_TOKEN not set! Bot will not start.")

# ==================== FLASK ROUTES ====================
@app.route('/')
def index():
    """Main page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return "Error loading page. Check that templates/index.html exists.", 500

@app.route('/game')
def game():
    """Serve game page"""
    try:
        user_id = request.args.get('user')
        if user_id and user_id != 'guest':
            user = get_user(int(user_id))
            if user:
                return render_template('index.html', 
                                     user_id=user_id,
                                     balance=user['balance'],
                                     username=user['first_name'])
        return render_template('index.html', user_id='guest', balance=1000, username='Player')
    except Exception as e:
        logger.error(f"Error in game route: {e}")
        return "Error loading game", 500

@app.route('/api/user/<int:telegram_id>')
def get_user_data(telegram_id):
    """Get user data for game"""
    user = get_user(telegram_id)
    if user:
        return jsonify({
            'success': True,
            'balance': user['balance'],
            'username': user['first_name']
        })
    return jsonify({'success': False, 'error': 'User not found'}), 404

@app.route('/api/game/settings')
def game_settings():
    """Get current game settings"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT game_type, card_price, prize_pool FROM game_settings ORDER BY updated_at DESC LIMIT 1")
    settings = c.fetchone()
    conn.close()
    
    if settings:
        return jsonify({
            'success': True,
            'game_type': settings[0],
            'card_price': settings[1],
            'prize_pool': settings[2]
        })
    return jsonify({
        'success': True,
        'game_type': 'full house',
        'card_price': 10,
        'prize_pool': 2000
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'bot_token_configured': bool(BOT_TOKEN),
        'bot_running': True
    })

@app.route('/test')
def test():
    """Test endpoint"""
    return jsonify({
        'message': 'Flask is working!',
        'bot_token': 'configured' if BOT_TOKEN else 'missing',
        'app_url': APP_URL
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)