import os
import sqlite3
import threading
import asyncio
import logging
import time
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
application = Flask(__name__)
app = application
app.secret_key = os.environ.get('SECRET_KEY', 'bingo-secret-key-2026')

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
RAILWAY_URL = os.environ.get('RAILWAY_STATIC_URL', 'localhost:5000')
APP_URL = f"https://{RAILWAY_URL}"

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")
logger.info(f"ADMIN_ID: {ADMIN_ID}")

# ==================== DATABASE SETUP ====================
def init_db():
    """Initialize database tables"""
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
                  phone_number TEXT,
                  is_admin BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Purchased cards table
    c.execute('''CREATE TABLE IF NOT EXISTS purchased_cards
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  card_number INTEGER UNIQUE,
                  user_id INTEGER,
                  session_id TEXT,
                  purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  status TEXT DEFAULT 'active',
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    # Transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount INTEGER DEFAULT 0,
                  tx_id TEXT UNIQUE,
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
                  min_cards_to_start INTEGER DEFAULT 10,
                  call_interval INTEGER DEFAULT 3,
                  house_fee REAL DEFAULT 5,
                  updated_by INTEGER,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Insert default settings if not exists
    c.execute("SELECT COUNT(*) FROM game_settings")
    if c.fetchone()[0] == 0:
        c.execute('''INSERT INTO game_settings 
                     (game_type, card_price, min_cards_to_start, call_interval, house_fee) 
                     VALUES (?, ?, ?, ?, ?)''',
                  ('full house', 10, 10, 3, 5))
    
    # Game sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS game_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT UNIQUE,
                  game_type TEXT,
                  card_price INTEGER,
                  total_cards_sold INTEGER DEFAULT 0,
                  total_players INTEGER DEFAULT 0,
                  prize_pool INTEGER DEFAULT 0,
                  status TEXT DEFAULT 'waiting',
                  started_at TIMESTAMP,
                  ended_at TIMESTAMP,
                  house_fee REAL DEFAULT 5,
                  house_collected INTEGER DEFAULT 0)''')
    
    # Game participants table
    c.execute('''CREATE TABLE IF NOT EXISTS game_participants
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  user_id INTEGER,
                  cards TEXT,
                  cards_bought INTEGER,
                  paid_amount INTEGER,
                  has_bingo BOOLEAN DEFAULT 0,
                  prize_won INTEGER DEFAULT 0,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id),
                  FOREIGN KEY (session_id) REFERENCES game_sessions(session_id))''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

init_db()

# ==================== FIX: ENSURE ADMIN USER IS SET ====================
def ensure_admin_user():
    """Make sure the ADMIN_ID user is set as admin in database"""
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.warning("No ADMIN_ID set in environment variables")
        return
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Check if user exists
    c.execute("SELECT id, is_admin FROM users WHERE telegram_id = ?", (ADMIN_ID,))
    user = c.fetchone()
    
    if user:
        # User exists, make sure they are admin
        if user[1] != 1:
            c.execute("UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (ADMIN_ID,))
            logger.info(f"User {ADMIN_ID} updated to admin")
        else:
            logger.info(f"User {ADMIN_ID} is already admin")
    else:
        # User doesn't exist, create them as admin
        c.execute('''INSERT INTO users 
                     (telegram_id, username, first_name, is_admin) 
                     VALUES (?, ?, ?, 1)''',
                  (ADMIN_ID, "admin", "Admin"))
        logger.info(f"Admin user {ADMIN_ID} created")
    
    conn.commit()
    conn.close()

ensure_admin_user()

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
            'phone_number': user[8],
            'is_admin': user[9],
            'created_at': user[10]
        }
    return None

def create_user(telegram_id, username, first_name):
    """Create new user"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
              (telegram_id, username, first_name))
    conn.commit()
    conn.close()

def update_balance(telegram_id, amount, operation='add'):
    """Update user balance"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    if operation == 'add':
        c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
    else:
        c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (amount, telegram_id))
    
    c.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
    new_balance = c.fetchone()[0]
    conn.commit()
    conn.close()
    return new_balance

def purchase_cards(user_id, card_numbers, session_id):
    """Purchase multiple cards"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    success = []
    failed = []
    
    for card in card_numbers:
        try:
            c.execute("INSERT INTO purchased_cards (card_number, user_id, session_id, status) VALUES (?, ?, ?, 'active')",
                      (card, user_id, session_id))
            success.append(card)
        except sqlite3.IntegrityError:
            failed.append(card)
    
    conn.commit()
    conn.close()
    return success, failed

def get_purchased_cards(session_id=None):
    """Get all purchased cards"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    if session_id:
        c.execute("SELECT card_number, user_id FROM purchased_cards WHERE session_id = ? AND status = 'active'", (session_id,))
    else:
        c.execute("SELECT card_number, user_id FROM purchased_cards WHERE status = 'active'")
    
    cards = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return cards

def get_user_cards(user_id):
    """Get cards purchased by a specific user"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT card_number FROM purchased_cards WHERE user_id = ? AND status = 'active'", (user_id,))
    cards = [row[0] for row in c.fetchall()]
    conn.close()
    return cards

# ==================== BOT SETUP ====================
def run_bot():
    """Run Telegram bot in a separate thread"""
    import asyncio
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
    
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    logger.info(f"Starting bot in thread...")
    
    # Create event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        logger.info(f"Start command from {user.first_name} (ID: {user.id})")
        
        # Check if user exists in database
        db_user = get_user(user.id)
        if not db_user:
            create_user(user.id, user.username, user.first_name)
            db_user = get_user(user.id)
        
        # Check if user is admin
        is_admin = db_user and db_user['is_admin']
        
        # Create main menu
        keyboard = [
            [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
            [
                InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
                InlineKeyboardButton("📊 STATS", callback_data="stats")
            ],
            [InlineKeyboardButton("💳 BALANCE", callback_data="balance")]
        ]
        
        if is_admin:
            keyboard.append([InlineKeyboardButton("👑 ADMIN PANEL", web_app={"url": f"{APP_URL}/admin?user={user.id}"})])
        
        balance = db_user['balance'] if db_user else 1000
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
            f"💰 Balance: {balance} ETB",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = query.from_user
        
        if data == "balance":
            db_user = get_user(user.id)
            if db_user:
                await query.edit_message_text(
                    f"💳 *Your Balance*\n\n"
                    f"Available: *{db_user['balance']} ETB*",
                    parse_mode='Markdown'
                )
        
        elif data == "stats":
            db_user = get_user(user.id)
            if db_user:
                await query.edit_message_text(
                    f"📊 *Your Stats*\n\n"
                    f"Games Played: *{db_user['games_played']}*\n"
                    f"Wins: *{db_user['wins']} ETB*",
                    parse_mode='Markdown'
                )
        
        elif data == "deposit":
            await query.edit_message_text(
                "💰 *Deposit Instructions*\n\n"
                "1. Send money via Telebirr to:\n"
                "   📱 +251 91 234 5678\n"
                "2. Send your transaction ID here",
                parse_mode='Markdown'
            )
            context.user_data['awaiting_deposit'] = True
    
    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        if context.user_data.get('awaiting_deposit'):
            await update.message.reply_text("✅ Deposit request received! Admin will verify.")
            context.user_data.clear()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info("Bot started polling...")
    
    try:
        application.run_polling(drop_pending_updates=True)
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
            'games': user['games_played'],
            'wins': user['wins'],
            'is_admin': user['is_admin']
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@application.route('/api/cards/status')
def get_card_status():
    """Get status of all cards"""
    user_id = request.args.get('user_id')
    cards = get_purchased_cards()
    
    my_cards = []
    if user_id:
        user = get_user(int(user_id))
        if user:
            my_cards = get_user_cards(user['id'])
    
    return jsonify({
        'success': True,
        'purchased': list(cards.keys()),
        'purchased_by': cards,
        'my_cards': my_cards
    })

@application.route('/api/game/session')
def get_game_session():
    """Get current game session"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT session_id, total_cards_sold, total_players, card_price, status FROM game_sessions WHERE status = 'waiting' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    
    if session:
        prize_pool = session[1] * session[3]
        
        c.execute('''SELECT u.telegram_id, u.first_name, p.cards_bought 
                     FROM game_participants p
                     JOIN users u ON p.user_id = u.id
                     WHERE p.session_id = ?''', (session[0],))
        players = [{'id': row[0], 'name': row[1], 'cards': row[2]} for row in c.fetchall()]
        
        conn.close()
        return jsonify({
            'success': True,
            'session_id': session[0],
            'total_cards_sold': session[1],
            'total_players': session[2],
            'prize_pool': prize_pool,
            'status': session[4],
            'players': players
        })
    
    conn.close()
    return jsonify({
        'success': True,
        'total_cards_sold': 0,
        'total_players': 0,
        'prize_pool': 0,
        'status': 'no_session'
    })

@application.route('/api/game/purchase', methods=['POST'])
def purchase_cards():
    """Purchase cards and join game"""
    data = request.json
    user_id = data.get('user_id')
    cards = data.get('cards', [])
    total_price = data.get('total_price', 0)
    
    user = get_user(int(user_id))
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Check balance
    if user['balance'] < total_price:
        return jsonify({'success': False, 'error': 'Insufficient balance'}), 400
    
    # Get or create session
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT session_id FROM game_sessions WHERE status = 'waiting' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    
    settings = get_game_settings()
    
    if not session:
        session_id = str(uuid.uuid4())[:8]
        c.execute('''INSERT INTO game_sessions 
                     (session_id, game_type, card_price, status, house_fee) 
                     VALUES (?, ?, ?, 'waiting', ?)''',
                  (session_id, settings['game_type'], settings['card_price'], settings['house_fee']))
    else:
        session_id = session[0]
    
    # Check if cards are available
    purchased = get_purchased_cards(session_id)
    conflicts = [c for c in cards if c in purchased]
    
    if conflicts:
        conn.close()
        return jsonify({
            'success': False,
            'error': 'Some cards already purchased',
            'conflicts': conflicts
        }), 409
    
    # Purchase cards
    success, failed = purchase_cards(user['id'], cards, session_id)
    
    # Update user balance
    new_balance = update_balance(user_id, total_price, 'subtract')
    
    # Add to game participants
    c.execute('''INSERT INTO game_participants 
                 (session_id, user_id, cards, cards_bought, paid_amount) 
                 VALUES (?, ?, ?, ?, ?)''',
              (session_id, user['id'], json.dumps(cards), len(cards), total_price))
    
    # Update session stats
    c.execute('''UPDATE game_sessions 
                 SET total_cards_sold = total_cards_sold + ?,
                     total_players = total_players + 1
                 WHERE session_id = ?''',
              (len(cards), session_id))
    
    # Get updated session info
    c.execute("SELECT total_cards_sold, total_players FROM game_sessions WHERE session_id = ?", (session_id,))
    updated = c.fetchone()
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'new_balance': new_balance,
        'session_id': session_id,
        'total_cards_sold': updated[0],
        'total_players': updated[1],
        'game_ready': updated[0] >= settings['min_cards_to_start']
    })

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot_token_configured': bool(BOT_TOKEN),
        'url': APP_URL
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)