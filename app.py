import os
import json
import sqlite3
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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
logger.info(f"APP_URL: {APP_URL}")

# ==================== DATABASE ====================
def init_db():
    """Initialize database"""
    os.makedirs('database', exist_ok=True)
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Users table with phone number
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  first_name TEXT,
                  phone_number TEXT,
                  balance INTEGER DEFAULT 1000,
                  games_played INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  total_deposits INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Game sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS game_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT UNIQUE,
                  total_cards_sold INTEGER DEFAULT 0,
                  total_players INTEGER DEFAULT 0,
                  status TEXT DEFAULT 'waiting',
                  started_at TIMESTAMP,
                  ended_at TIMESTAMP,
                  prize_pool INTEGER DEFAULT 0)''')
    
    # Game participants table
    c.execute('''CREATE TABLE IF NOT EXISTS game_participants
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  user_id INTEGER,
                  cards_bought INTEGER,
                  paid_amount INTEGER,
                  phone_number TEXT,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id),
                  FOREIGN KEY (session_id) REFERENCES game_sessions(session_id))''')
    
    # Game settings
    c.execute('''CREATE TABLE IF NOT EXISTS game_settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_type TEXT DEFAULT 'full house',
                  card_price INTEGER DEFAULT 10,
                  prize_pool INTEGER DEFAULT 2000,
                  min_cards_to_start INTEGER DEFAULT 10)''')
    
    # Insert default settings
    c.execute("SELECT COUNT(*) FROM game_settings")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO game_settings (game_type, card_price, prize_pool, min_cards_to_start) VALUES (?, ?, ?, ?)",
                  ('full house', 10, 2000, 10))
    
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
            'balance': user[5],
            'games_played': user[6],
            'wins': user[7],
            'total_deposits': user[8],
            'created_at': user[9]
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

def update_user_phone(telegram_id, phone_number):
    """Update user's phone number"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET phone_number = ? WHERE telegram_id = ?",
                  (phone_number, telegram_id))
        conn.commit()
        logger.info(f"Phone number updated for {telegram_id}: {phone_number}")
        return True
    except Exception as e:
        logger.error(f"Error updating phone: {e}")
        return False
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
    c.execute("SELECT game_type, card_price, prize_pool, min_cards_to_start FROM game_settings LIMIT 1")
    settings = c.fetchone()
    conn.close()
    
    if settings:
        return {
            'game_type': settings[0],
            'card_price': settings[1],
            'prize_pool': settings[2],
            'min_cards_to_start': settings[3]
        }
    return {'game_type': 'full house', 'card_price': 10, 'prize_pool': 2000, 'min_cards_to_start': 10}

def get_current_session():
    """Get current active game session"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT * FROM game_sessions WHERE status = 'waiting' OR status = 'countdown' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    conn.close()
    
    if session:
        return {
            'id': session[0],
            'session_id': session[1],
            'total_cards_sold': session[2],
            'total_players': session[3],
            'status': session[4],
            'started_at': session[5],
            'ended_at': session[6],
            'prize_pool': session[7]
        }
    return None

def create_new_session():
    """Create a new game session"""
    import uuid
    session_id = str(uuid.uuid4())[:8]
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("INSERT INTO game_sessions (session_id, status) VALUES (?, 'waiting')", (session_id,))
    conn.commit()
    conn.close()
    
    logger.info(f"New game session created: {session_id}")
    return session_id

def add_participant(session_id, user_id, cards_bought, paid_amount, phone_number=None):
    """Add a participant to the game session"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Add participant
    c.execute('''INSERT INTO game_participants 
                 (session_id, user_id, cards_bought, paid_amount, phone_number)
                 VALUES (?, ?, ?, ?, ?)''',
              (session_id, user_id, cards_bought, paid_amount, phone_number))
    
    # Update session stats
    c.execute('''UPDATE game_sessions 
                 SET total_cards_sold = total_cards_sold + ?,
                     total_players = total_players + 1,
                     prize_pool = prize_pool + ?
                 WHERE session_id = ?''',
              (cards_bought, paid_amount, session_id))
    
    conn.commit()
    conn.close()
    
    # Get updated session
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT total_cards_sold, total_players, prize_pool FROM game_sessions WHERE session_id = ?", (session_id,))
    result = c.fetchone()
    conn.close()
    
    return {
        'total_cards_sold': result[0],
        'total_players': result[1],
        'prize_pool': result[2]
    }

def update_session_status(session_id, status):
    """Update session status"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    if status == 'countdown':
        c.execute("UPDATE game_sessions SET status = ?, started_at = ? WHERE session_id = ?",
                  (status, datetime.now(), session_id))
    elif status == 'active':
        c.execute("UPDATE game_sessions SET status = ? WHERE session_id = ?", (status, session_id))
    elif status == 'completed':
        c.execute("UPDATE game_sessions SET status = ?, ended_at = ? WHERE session_id = ?",
                  (status, datetime.now(), session_id))
    
    conn.commit()
    conn.close()

def get_participants(session_id):
    """Get all participants in a session with their phone numbers"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''SELECT u.telegram_id, u.username, u.first_name, u.phone_number, p.cards_bought 
                 FROM game_participants p
                 JOIN users u ON p.user_id = u.id
                 WHERE p.session_id = ?''', (session_id,))
    participants = c.fetchall()
    conn.close()
    
    return [{
        'telegram_id': p[0],
        'username': p[1],
        'first_name': p[2],
        'phone_number': p[3],
        'cards_bought': p[4]
    } for p in participants]

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
        
        # Check if phone number is needed
        if not db_user['phone_number']:
            # Ask for phone number
            contact_keyboard = [
                [KeyboardButton("📱 Share Phone Number", request_contact=True)],
                [KeyboardButton("❌ Skip for now")]
            ]
            reply_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(
                "📱 *Please share your phone number*\n\n"
                "This helps us verify your identity for payments and withdrawals.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Get current game session
        session = get_current_session()
        if session:
            cards_needed = max(0, 10 - session['total_cards_sold'])
            status_text = f"\n\n🎮 Current game: {session['total_cards_sold']}/10 cards sold"
        else:
            status_text = "\n\n🎮 No active game. Be the first to join!"
        
        # Create Web App button
        keyboard = [
            [InlineKeyboardButton(
                "🎮 PLAY BINGO",
                web_app={"url": f"{APP_URL}/game?user={telegram_id}"}
            )],
            [InlineKeyboardButton("💰 BALANCE", callback_data="balance")],
            [InlineKeyboardButton("📞 MY PHONE", callback_data="show_phone")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
            f"💰 Balance: {db_user['balance']} ETB"
            f"{status_text}",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shared contact information"""
    contact = update.message.contact
    user = update.effective_user
    
    if contact and contact.user_id == user.id:
        phone_number = contact.phone_number
        # Save phone number to database
        if update_user_phone(user.id, phone_number):
            await update.message.reply_text(
                f"✅ *Phone number saved!*\n\n"
                f"📞 {phone_number}\n\n"
                f"Use /start to continue.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Error saving phone number. Please try again.")
    else:
        await update.message.reply_text("❌ Please share your own contact information.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "balance":
        user = get_user(query.from_user.id)
        if user:
            await query.edit_message_text(f"💰 Your balance: {user['balance']} ETB")
    
    elif query.data == "show_phone":
        user = get_user(query.from_user.id)
        if user and user['phone_number']:
            await query.edit_message_text(f"📞 Your phone number: {user['phone_number']}")
        else:
            await query.edit_message_text("❌ No phone number on file. Please use /start to add one.")

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
        application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        
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
            return render_template('index.html', 
                                 user_id=user_id, 
                                 balance=user['balance'],
                                 phone=user['phone_number'] or '')
    return render_template('index.html', user_id='guest', balance=1000, phone='')

@app.route('/api/user/<int:telegram_id>')
def get_user_data(telegram_id):
    user = get_user(telegram_id)
    if user:
        return jsonify({
            'success': True, 
            'balance': user['balance'],
            'phone': user['phone_number'] or ''
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.route('/api/game/settings')
def game_settings_api():
    settings = get_game_settings()
    return jsonify({'success': True, **settings})

@app.route('/api/game/session')
def get_game_session():
    """Get current game session info"""
    session = get_current_session()
    if session:
        return jsonify({
            'success': True,
            'total_cards_sold': session['total_cards_sold'],
            'total_players': session['total_players'],
            'prize_pool': session['prize_pool'],
            'status': session['status'],
            'cards_needed': max(0, 10 - session['total_cards_sold'])
        })
    else:
        return jsonify({
            'success': True,
            'total_cards_sold': 0,
            'total_players': 0,
            'prize_pool': 0,
            'status': 'no_session',
            'cards_needed': 10
        })

@app.route('/api/game/purchase', methods=['POST'])
def purchase_cards():
    """Handle card purchase"""
    data = request.json
    telegram_id = data.get('user_id')
    cards_bought = data.get('cards_bought', 0)
    total_paid = data.get('total_paid', 0)
    phone_number = data.get('phone_number')
    
    user = get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Update user balance
    new_balance = update_balance(telegram_id, total_paid, 'subtract')
    
    # Get or create game session
    session = get_current_session()
    if not session:
        session_id = create_new_session()
    else:
        session_id = session['session_id']
    
    # Add participant
    session_stats = add_participant(session_id, user['id'], cards_bought, total_paid, phone_number)
    
    # Check if we've reached 10 cards
    if session_stats['total_cards_sold'] >= 10:
        update_session_status(session_id, 'countdown')
        
        # Get all participants to potentially notify them
        participants = get_participants(session_id)
        # You could send notifications here if needed
    
    return jsonify({
        'success': True,
        'new_balance': new_balance,
        'session': session_stats,
        'game_ready': session_stats['total_cards_sold'] >= 10
    })

@app.route('/api/game/participants/<session_id>')
def get_game_participants(session_id):
    """Get all participants in a session"""
    participants = get_participants(session_id)
    return jsonify({
        'success': True,
        'participants': participants
    })

@app.route('/health')
def health():
    session = get_current_session()
    return jsonify({
        'status': 'healthy',
        'bot': 'running' if BOT_TOKEN else 'no token',
        'current_session': session['total_cards_sold'] if session else 0
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)