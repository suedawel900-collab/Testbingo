import os
import sqlite3
import multiprocessing
import logging
import time
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session

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

# IMPORTANT: Only run bot in the main process, not in Gunicorn workers
IS_MAIN_PROCESS = os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('GUNICORN_WORKER_ID')

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")
logger.info(f"IS_MAIN_PROCESS: {IS_MAIN_PROCESS}")
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
    
    # Purchased cards table - NEW
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
    
    # Game settings table with house fee
    c.execute('''CREATE TABLE IF NOT EXISTS game_settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_type TEXT DEFAULT 'full house',
                  card_price INTEGER DEFAULT 10,
                  prize_pool INTEGER DEFAULT 2000,
                  min_cards_to_start INTEGER DEFAULT 10,
                  call_interval INTEGER DEFAULT 3,
                  house_fee REAL DEFAULT 5,
                  updated_by INTEGER,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Insert default settings if not exists
    c.execute("SELECT COUNT(*) FROM game_settings")
    if c.fetchone()[0] == 0:
        c.execute('''INSERT INTO game_settings 
                     (game_type, card_price, prize_pool, min_cards_to_start, call_interval, house_fee) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  ('full house', 10, 2000, 10, 3, 5))
    
    # Game sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS game_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT UNIQUE,
                  game_type TEXT,
                  card_price INTEGER,
                  prize_pool INTEGER,
                  total_cards_sold INTEGER DEFAULT 0,
                  total_players INTEGER DEFAULT 0,
                  status TEXT DEFAULT 'waiting',
                  started_at TIMESTAMP,
                  ended_at TIMESTAMP,
                  winner_id INTEGER,
                  winning_card TEXT,
                  house_fee REAL DEFAULT 5,
                  house_collected INTEGER DEFAULT 0)''')
    
    # Game participants table
    c.execute('''CREATE TABLE IF NOT EXISTS game_participants
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  user_id INTEGER,
                  cards TEXT,  -- JSON array of card numbers
                  cards_bought INTEGER,
                  paid_amount INTEGER,
                  has_bingo BOOLEAN DEFAULT 0,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id),
                  FOREIGN KEY (session_id) REFERENCES game_sessions(session_id))''')
    
    # Admin logs table
    c.execute('''CREATE TABLE IF NOT EXISTS admin_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER,
                  action TEXT,
                  details TEXT,
                  ip_address TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (admin_id) REFERENCES users(id))''')
    
    # House fee history table
    c.execute('''CREATE TABLE IF NOT EXISTS house_fee_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  total_prize INTEGER,
                  fee_percentage REAL,
                  house_amount INTEGER,
                  players_prize INTEGER,
                  game_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
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

# Call this after database initialization
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

def update_user_phone(telegram_id, phone_number):
    """Update user's phone number"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("UPDATE users SET phone_number = ? WHERE telegram_id = ?",
              (phone_number, telegram_id))
    conn.commit()
    conn.close()

def add_transaction(user_id, amount, tx_id):
    """Add new transaction"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute("INSERT INTO transactions (user_id, amount, tx_id, receipt_url) VALUES (?, ?, ?, ?)",
              (user_id, amount, tx_id, receipt_url))
    conn.commit()
    conn.close()

def approve_transaction(tx_id, admin_id):
    """Approve transaction and update user balance"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute('''UPDATE transactions 
                 SET status = 'approved', approved_by = ?, approved_at = ? 
                 WHERE tx_id = ?''', 
              (admin_id, datetime.now(), tx_id))
    
    c.execute("SELECT user_id, amount FROM transactions WHERE tx_id = ?", (tx_id,))
    result = c.fetchone()
    if not result:
        conn.close()
        return None, None
    
    user_id, amount = result
    
    c.execute("UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE id = ?",
              (amount, amount, user_id))
    
    c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
    telegram_id = c.fetchone()[0]
    
    conn.commit()
    conn.close()
    return telegram_id, amount

def get_game_settings():
    """Get current game settings"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT game_type, card_price, prize_pool, min_cards_to_start, call_interval, house_fee FROM game_settings ORDER BY updated_at DESC LIMIT 1")
    settings = c.fetchone()
    conn.close()
    
    if settings:
        return {
            'game_type': settings[0],
            'card_price': settings[1],
            'prize_pool': settings[2],
            'min_cards_to_start': settings[3],
            'call_interval': settings[4],
            'house_fee': settings[5]
        }
    return {'game_type': 'full house', 'card_price': 10, 'prize_pool': 2000, 
            'min_cards_to_start': 10, 'call_interval': 3, 'house_fee': 5}

def update_game_settings(admin_id, settings):
    """Update game settings"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''INSERT INTO game_settings 
                 (game_type, card_price, prize_pool, min_cards_to_start, call_interval, house_fee, updated_by) 
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (settings['game_type'], settings['card_price'], settings['prize_pool'], 
               settings['min_cards_to_start'], settings['call_interval'], 
               settings.get('house_fee', 5), admin_id))
    conn.commit()
    conn.close()
    
    log_admin_action(admin_id, 'update_settings', json.dumps(settings))

def get_pending_transactions():
    """Get all pending transactions"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''SELECT t.id, u.username, u.first_name, u.telegram_id, t.amount, t.tx_id, t.created_at 
                 FROM transactions t
                 JOIN users u ON t.user_id = u.id
                 WHERE t.status = 'pending'
                 ORDER BY t.created_at DESC''')
    transactions = c.fetchall()
    conn.close()
    
    result = []
    for t in transactions:
        result.append({
            'id': t[0],
            'username': t[1],
            'name': t[2],
            'telegram_id': t[3],
            'amount': t[4],
            'tx_id': t[5],
            'created_at': t[6]
        })
    return result

def get_all_users():
    """Get all users"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''SELECT id, telegram_id, username, first_name, balance, games_played, wins, total_deposits, phone_number, is_admin 
                 FROM users ORDER BY balance DESC''')
    users = c.fetchall()
    conn.close()
    
    result = []
    for u in users:
        result.append({
            'id': u[0],
            'telegram_id': u[1],
            'username': u[2],
            'name': u[3],
            'balance': u[4],
            'games_played': u[5],
            'wins': u[6],
            'total_deposits': u[7],
            'phone': u[8],
            'is_admin': u[9]
        })
    return result

def get_game_stats():
    """Get game statistics"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Total users
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    # Total transactions
    c.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE status = 'approved'")
    row = c.fetchone()
    tx_count = row[0] or 0
    tx_total = row[1] or 0
    
    # Total games played
    c.execute("SELECT SUM(games_played) FROM users")
    total_games = c.fetchone()[0] or 0
    
    # Active game session
    c.execute("SELECT COUNT(*) FROM game_sessions WHERE status = 'active'")
    active_games = c.fetchone()[0]
    
    # Pending transactions count
    c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
    pending_count = c.fetchone()[0]
    
    # Total house collected
    c.execute("SELECT SUM(house_collected) FROM game_sessions")
    house_total = c.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'total_users': total_users,
        'total_transactions': tx_count,
        'total_deposits': tx_total,
        'total_games': total_games,
        'active_games': active_games,
        'pending_count': pending_count,
        'house_total': house_total
    }

def log_admin_action(admin_id, action, details):
    """Log admin action"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (admin_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
              (admin_id, action, details, request.remote_addr))
    conn.commit()
    conn.close()

def create_game_session(settings):
    """Create a new game session"""
    session_id = str(uuid.uuid4())[:8]
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''INSERT INTO game_sessions 
                 (session_id, game_type, card_price, prize_pool, status, started_at, house_fee) 
                 VALUES (?, ?, ?, ?, 'active', ?, ?)''',
              (session_id, settings['game_type'], settings['card_price'], 
               settings['prize_pool'], datetime.now(), settings.get('house_fee', 5)))
    conn.commit()
    conn.close()
    
    return session_id

def end_game_session(session_id, winner_id, winning_card):
    """End a game session and calculate house fee"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Get session details
    c.execute("SELECT prize_pool, house_fee FROM game_sessions WHERE session_id = ?", (session_id,))
    session = c.fetchone()
    
    if session:
        prize_pool, house_fee = session
        house_amount = int(prize_pool * house_fee / 100)
        players_prize = prize_pool - house_amount
        
        # Update session
        c.execute('''UPDATE game_sessions 
                     SET status = 'ended', ended_at = ?, winner_id = ?, 
                         winning_card = ?, house_collected = ?
                     WHERE session_id = ?''',
                  (datetime.now(), winner_id, winning_card, house_amount, session_id))
        
        # Add to house fee history
        c.execute('''INSERT INTO house_fee_history 
                     (session_id, total_prize, fee_percentage, house_amount, players_prize) 
                     VALUES (?, ?, ?, ?, ?)''',
                  (session_id, prize_pool, house_fee, house_amount, players_prize))
    
    conn.commit()
    conn.close()

# ==================== CARD PURCHASE FUNCTIONS ====================
def check_cards_available(card_numbers):
    """Check if cards are available for purchase"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    placeholders = ','.join(['?'] * len(card_numbers))
    c.execute(f"SELECT card_number FROM purchased_cards WHERE card_number IN ({placeholders}) AND status = 'active'", card_numbers)
    purchased = [row[0] for row in c.fetchall()]
    
    conn.close()
    return purchased

def purchase_cards(user_id, card_numbers, session_id=None):
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

def get_user_cards(user_id):
    """Get all cards purchased by a user"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT card_number FROM purchased_cards WHERE user_id = ? AND status = 'active'", (user_id,))
    cards = [row[0] for row in c.fetchall()]
    conn.close()
    return cards

def get_all_purchased_cards():
    """Get all purchased cards (for grid display)"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT card_number, user_id FROM purchased_cards WHERE status = 'active'")
    cards = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return cards

# ==================== BOT PROCESS ====================
def run_bot_process():
    """Run bot in a separate process"""
    import asyncio
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
    from telegram.error import Conflict
    
    logger.info(f"Bot process started with PID: {os.getpid()}")
    
    # Database functions for bot process
    def bot_get_user(telegram_id):
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = c.fetchone()
        conn.close()
        return user
    
    def bot_create_user(telegram_id, username, first_name):
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                  (telegram_id, username, first_name))
        conn.commit()
        conn.close()
    
    def bot_update_phone(telegram_id, phone_number):
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("UPDATE users SET phone_number = ? WHERE telegram_id = ?",
                  (phone_number, telegram_id))
        conn.commit()
        conn.close()
    
    def bot_add_transaction(user_id, amount, tx_id):
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
        c.execute("INSERT INTO transactions (user_id, amount, tx_id, receipt_url) VALUES (?, ?, ?, ?)",
                  (user_id, amount, tx_id, receipt_url))
        conn.commit()
        conn.close()
    
    # ==================== BOT HANDLERS ====================
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"Start from {user.first_name} (ID: {user.id})")
        
        # Get or create user
        db_user = bot_get_user(user.id)
        if not db_user:
            bot_create_user(user.id, user.username, user.first_name)
            db_user = bot_get_user(user.id)
            
            if not db_user:
                await update.message.reply_text("❌ Error creating user. Please try again.")
                return
        
        # Check if user is admin
        is_admin = False
        if db_user and len(db_user) > 9:
            is_admin = db_user[9] == 1
            if is_admin:
                logger.info(f"✅ User {user.id} is an ADMIN")
        
        # Check if phone number exists
        phone_number = db_user[8] if db_user and len(db_user) > 8 else None
        
        if not phone_number:
            contact_keyboard = [
                [KeyboardButton("📱 Share Phone Number", request_contact=True)],
                [KeyboardButton("❌ Skip")]
            ]
            reply_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await update.message.reply_text(
                "📱 Please share your phone number for verification:",
                reply_markup=reply_markup
            )
            return
        
        # Create main menu buttons
        keyboard = [
            [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
            [
                InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
                InlineKeyboardButton("📊 STATS", callback_data="stats")
            ],
            [InlineKeyboardButton("💳 BALANCE", callback_data="balance")]
        ]
        
        # ADD ADMIN BUTTON IF USER IS ADMIN
        if is_admin:
            keyboard.append([InlineKeyboardButton("👑 ADMIN PANEL", web_app={"url": f"{APP_URL}/admin?user={user.id}"})])
        
        balance = db_user[4] if db_user and len(db_user) > 4 else 1000
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
            f"💰 Balance: {balance} ETB",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        user = update.effective_user
        
        if contact and contact.user_id == user.id:
            bot_update_phone(user.id, contact.phone_number)
            await update.message.reply_text(f"✅ Phone number saved!")
            
            # Get updated user
            db_user = bot_get_user(user.id)
            
            # Check if admin
            is_admin = False
            if db_user and len(db_user) > 9:
                is_admin = db_user[9] == 1
            
            balance = db_user[4] if db_user and len(db_user) > 4 else 1000
            
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
            
            await update.message.reply_text(
                f"🎰 You can now play!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text("❌ Please share your own contact")
    
    async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = query.from_user
        
        if data == "balance":
            db_user = bot_get_user(user.id)
            balance = db_user[4] if db_user and len(db_user) > 4 else 1000
            total_deposits = db_user[7] if db_user and len(db_user) > 7 else 0
            
            await query.edit_message_text(
                f"💳 *Your Balance*\n\n"
                f"Available: *{balance} ETB*\n"
                f"Total Deposits: *{total_deposits} ETB*",
                parse_mode='Markdown'
            )
        
        elif data == "stats":
            db_user = bot_get_user(user.id)
            balance = db_user[4] if db_user and len(db_user) > 4 else 1000
            games_played = db_user[5] if db_user and len(db_user) > 5 else 0
            wins = db_user[6] if db_user and len(db_user) > 6 else 0
            
            await query.edit_message_text(
                f"📊 *Your Stats*\n\n"
                f"Balance: *{balance} ETB*\n"
                f"Games Played: *{games_played}*\n"
                f"Wins: *{wins} ETB*",
                parse_mode='Markdown'
            )
        
        elif data == "deposit":
            await query.edit_message_text(
                "💰 *Enter Deposit Amount*\n\n"
                "Please enter the amount you want to deposit (in ETB):\n"
                "Minimum: 50 ETB\n\n"
                "Example: `100`",
                parse_mode='Markdown'
            )
            context.user_data['awaiting_amount'] = True
        
        elif data.startswith("approve_"):
            if user.id != ADMIN_ID:
                await query.edit_message_text("❌ Unauthorized")
                return
            
            tx_id = data.replace("approve_", "")
            
            conn = sqlite3.connect('database/bingo.db')
            c = conn.cursor()
            c.execute('''UPDATE transactions SET status='approved', approved_by=?, approved_at=? WHERE tx_id=?''',
                      (ADMIN_ID, datetime.now(), tx_id))
            c.execute("SELECT user_id, amount FROM transactions WHERE tx_id=?", (tx_id,))
            result = c.fetchone()
            if result:
                user_id, amount = result
                c.execute("UPDATE users SET balance=balance+?, total_deposits=total_deposits+? WHERE id=?", 
                         (amount, amount, user_id))
                c.execute("SELECT telegram_id FROM users WHERE id=?", (user_id,))
                telegram_id = c.fetchone()[0]
                
                await context.bot.send_message(
                    telegram_id, 
                    f"✅ *Deposit Approved!*\n\n"
                    f"Amount: *{amount} ETB*\n"
                    f"Transaction ID: `{tx_id}`",
                    parse_mode='Markdown'
                )
            
            conn.commit()
            conn.close()
            
            await query.edit_message_text(
                f"✅ *Deposit Approved*",
                parse_mode='Markdown'
            )
        
        elif data.startswith("reject_"):
            if user.id != ADMIN_ID:
                await query.edit_message_text("❌ Unauthorized")
                return
            
            tx_id = data.replace("reject_", "")
            
            conn = sqlite3.connect('database/bingo.db')
            c = conn.cursor()
            c.execute("UPDATE transactions SET status='rejected' WHERE tx_id=?", (tx_id,))
            conn.commit()
            conn.close()
            
            await query.edit_message_text(f"❌ Deposit Rejected")
    
    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        text = update.message.text.strip()
        
        if context.user_data.get('awaiting_amount'):
            try:
                amount = int(text)
                if amount < 50:
                    await update.message.reply_text("❌ Minimum deposit is 50 ETB")
                    return
                
                context.user_data['deposit_amount'] = amount
                context.user_data['awaiting_amount'] = False
                context.user_data['awaiting_tx'] = True
                
                await update.message.reply_text(
                    "💰 *Enter Transaction ID*\n\n"
                    "Please send the Telebirr transaction ID you received:\n\n"
                    "Example: `DC39E2J9ZP`",
                    parse_mode='Markdown'
                )
                
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number")
        
        elif context.user_data.get('awaiting_tx'):
            tx_id = text.upper()
            amount = context.user_data.get('deposit_amount')
            
            if not amount:
                await update.message.reply_text("❌ Please start over with /start")
                context.user_data.clear()
                return
            
            db_user = bot_get_user(user.id)
            if not db_user:
                await update.message.reply_text("❌ User not found. Please use /start")
                return
            
            bot_add_transaction(db_user[0], amount, tx_id)
            
            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{tx_id}")
            ]]
            
            receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
            
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 *New Deposit Request*\n\n"
                f"👤 User: @{user.username or 'No username'}\n"
                f"🆔 ID: {user.id}\n"
                f"💳 Amount: *{amount} ETB*\n"
                f"🔑 TX ID: `{tx_id}`\n\n"
                f"[View Receipt]({receipt_url})",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            await update.message.reply_text(
                f"✅ *Deposit Request Sent!*\n\n"
                f"Amount: *{amount} ETB*\n"
                f"Transaction ID: `{tx_id}`\n\n"
                f"Admin will approve within 5 minutes.",
                parse_mode='Markdown'
            )
            
            context.user_data.clear()
    
    # Create and run application
    try:
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CallbackQueryHandler(button_handler))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("Bot process starting polling...")
        bot_app.run_polling(drop_pending_updates=True)
        
    except Conflict as e:
        logger.error(f"Conflict error - another bot instance is running: {e}")
    except Exception as e:
        logger.error(f"Bot process error: {e}")
        time.sleep(5)

# ==================== START BOT PROCESS ====================
bot_process = None

def start_bot_process():
    """Start the bot in a separate process - ONLY ONCE"""
    global bot_process
    
    if not IS_MAIN_PROCESS:
        logger.info("Skipping bot start in Gunicorn worker")
        return
    
    if bot_process and bot_process.is_alive():
        logger.info("Bot process already running")
        return
    
    # Try to kill any existing bot processes
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] != current_pid and 'python' in proc.info['name']:
                    cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                    if 'bot' in cmdline.lower() or 'run_bot_process' in cmdline:
                        logger.info(f"Killing old bot process: {proc.info['pid']}")
                        proc.kill()
            except:
                pass
    except:
        pass
    
    bot_process = multiprocessing.Process(target=run_bot_process, daemon=True)
    bot_process.start()
    logger.info(f"Bot process started with PID: {bot_process.pid}")

if BOT_TOKEN and IS_MAIN_PROCESS:
    start_bot_process()

# ==================== FLASK ROUTES ====================

# Player routes
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

# ==================== CARD PURCHASE API ====================
@application.route('/api/cards/status')
def get_card_status():
    """Get status of all cards (which are purchased)"""
    purchased = get_all_purchased_cards()
    
    # Get user's cards if user_id provided
    user_id = request.args.get('user_id')
    my_cards = []
    if user_id:
        my_cards = get_user_cards(int(user_id))
    
    return jsonify({
        'success': True,
        'purchased': list(purchased.keys()),
        'purchased_by': purchased,
        'my_cards': my_cards
    })

@application.route('/api/cards/purchase', methods=['POST'])
def purchase_cards_api():
    """Purchase multiple cards at once"""
    data = request.json
    user_id = data.get('user_id')
    cards = data.get('cards', [])
    total_price = data.get('total_price', 0)
    
    if not user_id or not cards:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    # Get current game session
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT session_id FROM game_sessions WHERE status = 'waiting' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    session_id = session[0] if session else None
    conn.close()
    
    # Check if cards are available
    conflicts = check_cards_available(cards)
    if conflicts:
        return jsonify({
            'success': False,
            'error': 'Some cards already purchased',
            'conflicts': conflicts
        }), 409
    
    # Purchase cards
    success, failed = purchase_cards(user_id, cards, session_id)
    
    # Update user balance
    user = get_user(int(user_id))
    if user and user['balance'] >= total_price:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", 
                  (total_price, user_id))
        conn.commit()
        conn.close()
    else:
        return jsonify({'success': False, 'error': 'Insufficient balance'}), 400
    
    return jsonify({
        'success': True,
        'purchased': success,
        'failed': failed
    })

@application.route('/api/game/session')
def get_game_session():
    """Get current game session info"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Get active or waiting session
    c.execute("SELECT session_id, total_cards_sold, total_players, prize_pool, status, house_fee FROM game_sessions WHERE status IN ('waiting', 'countdown', 'active') ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    
    if session:
        # Get players in this session
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
            'prize_pool': session[3],
            'status': session[4],
            'house_fee': session[5],
            'players': players
        })
    else:
        conn.close()
        return jsonify({
            'success': True,
            'total_cards_sold': 0,
            'total_players': 0,
            'prize_pool': 0,
            'status': 'no_session'
        })

@application.route('/api/game/join', methods=['POST'])
def join_game():
    """Player joins a game session"""
    data = request.json
    user_id = data.get('user_id')
    cards = data.get('cards', [])
    total_paid = data.get('total_paid', 0)
    
    user = get_user(int(user_id))
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Get or create session
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT id, session_id, total_cards_sold, total_players FROM game_sessions WHERE status = 'waiting' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    
    if not session:
        # Create new session
        settings = get_game_settings()
        session_id = str(uuid.uuid4())[:8]
        c.execute('''INSERT INTO game_sessions 
                     (session_id, game_type, card_price, prize_pool, status, house_fee) 
                     VALUES (?, ?, ?, ?, 'waiting', ?)''',
                  (session_id, settings['game_type'], settings['card_price'], 
                   settings['prize_pool'], settings['house_fee']))
        session_id = session_id
        session_cards = 0
        session_players = 0
    else:
        session_id = session[1]
        session_cards = session[2]
        session_players = session[3]
    
    # Add participant
    c.execute('''INSERT INTO game_participants 
                 (session_id, user_id, cards, cards_bought, paid_amount) 
                 VALUES (?, ?, ?, ?, ?)''',
              (session_id, user['id'], json.dumps(cards), len(cards), total_paid))
    
    # Update session stats
    c.execute('''UPDATE game_sessions 
                 SET total_cards_sold = total_cards_sold + ?,
                     total_players = total_players + 1,
                     prize_pool = prize_pool + ?
                 WHERE session_id = ?''',
              (len(cards), total_paid, session_id))
    
    conn.commit()
    
    # Get updated session
    c.execute("SELECT total_cards_sold, total_players, prize_pool FROM game_sessions WHERE session_id = ?", (session_id,))
    updated = c.fetchone()
    conn.close()
    
    return jsonify({
        'success': True,
        'session_id': session_id,
        'total_cards_sold': updated[0],
        'total_players': updated[1],
        'prize_pool': updated[2],
        'game_ready': updated[0] >= 10
    })

# ==================== ADMIN ROUTES ====================

@application.route('/admin')
def admin_panel():
    """Admin panel page"""
    user_id = request.args.get('user')
    if not user_id:
        return "Unauthorized - No user ID", 401
    
    user = get_user(int(user_id))
    if not user:
        return f"Unauthorized - User {user_id} not found", 401
    
    if not user['is_admin']:
        return f"Unauthorized - User {user_id} is not admin", 401
    
    logger.info(f"Admin panel accessed by user {user_id}")
    return render_template('admin.html', admin_id=user_id, admin_name=user['first_name'])

@application.route('/api/admin/check/<int:telegram_id>')
def check_admin(telegram_id):
    """Check if user is admin"""
    user = get_user(telegram_id)
    if user and user['is_admin']:
        return jsonify({'success': True, 'is_admin': True})
    return jsonify({'success': False, 'is_admin': False}), 403

@application.route('/api/admin/stats')
def admin_stats():
    """Get admin statistics"""
    admin_id = request.args.get('admin_id')
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    stats = get_game_stats()
    settings = get_game_settings()
    
    return jsonify({
        'success': True,
        'stats': stats,
        'settings': settings
    })

@application.route('/api/admin/users')
def admin_users():
    """Get all users"""
    admin_id = request.args.get('admin_id')
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    users = get_all_users()
    return jsonify({'success': True, 'users': users})

@application.route('/api/admin/transactions')
def admin_transactions():
    """Get pending transactions"""
    admin_id = request.args.get('admin_id')
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    transactions = get_pending_transactions()
    return jsonify({'success': True, 'transactions': transactions})

@application.route('/api/admin/update-settings', methods=['POST'])
def update_settings():
    """Update game settings"""
    data = request.json
    admin_id = data.get('admin_id')
    
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    settings = {
        'game_type': data.get('game_type', 'full house'),
        'card_price': int(data.get('card_price', 10)),
        'prize_pool': int(data.get('prize_pool', 2000)),
        'min_cards_to_start': int(data.get('min_cards_to_start', 10)),
        'call_interval': int(data.get('call_interval', 3)),
        'house_fee': float(data.get('house_fee', 5))
    }
    
    update_game_settings(user['id'], settings)
    
    return jsonify({'success': True})

@application.route('/api/admin/approve-transaction', methods=['POST'])
def admin_approve_transaction():
    """Approve a transaction"""
    data = request.json
    admin_id = data.get('admin_id')
    tx_id = data.get('tx_id')
    
    if not admin_id or not tx_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    telegram_id, amount = approve_transaction(tx_id, user['id'])
    
    if telegram_id:
        log_admin_action(user['id'], 'approve_transaction', f'{amount} ETB for {telegram_id}')
        return jsonify({
            'success': True,
            'message': f'Approved {amount} ETB for user {telegram_id}'
        })
    else:
        return jsonify({'success': False, 'error': 'Transaction not found'})

@application.route('/api/admin/reject-transaction', methods=['POST'])
def admin_reject_transaction():
    """Reject a transaction"""
    data = request.json
    admin_id = data.get('admin_id')
    tx_id = data.get('tx_id')
    
    if not admin_id or not tx_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("UPDATE transactions SET status='rejected' WHERE tx_id=?", (tx_id,))
    conn.commit()
    conn.close()
    
    log_admin_action(user['id'], 'reject_transaction', tx_id)
    
    return jsonify({'success': True})

@application.route('/api/admin/update-balance', methods=['POST'])
def admin_update_balance():
    """Manually update user balance"""
    data = request.json
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    amount = int(data.get('amount', 0))
    operation = data.get('operation', 'add')
    
    if not admin_id or not target_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    if operation == 'add':
        c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", 
                  (amount, target_id))
    else:
        c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", 
                  (amount, target_id))
    
    c.execute("SELECT balance FROM users WHERE telegram_id = ?", (target_id,))
    new_balance = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    log_admin_action(user['id'], f'update_balance_{operation}', f'{target_id}: {amount} ETB')
    
    return jsonify({'success': True, 'new_balance': new_balance})

@application.route('/api/admin/set-admin', methods=['POST'])
def set_admin():
    """Set or remove admin status for a user"""
    data = request.json
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    is_admin = data.get('is_admin', 0)
    
    if not admin_id or not target_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    admin_user = get_user(int(admin_id))
    if not admin_user or not admin_user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin = ? WHERE telegram_id = ?", (is_admin, target_id))
    conn.commit()
    conn.close()
    
    log_admin_action(admin_user['id'], 'set_admin', f'{target_id} -> {is_admin}')
    
    return jsonify({'success': True})

@application.route('/api/admin/add-user', methods=['POST'])
def add_user():
    """Add a new user manually"""
    data = request.json
    admin_id = data.get('admin_id')
    telegram_id = data.get('telegram_id')
    username = data.get('username', '')
    first_name = data.get('first_name', 'New User')
    phone = data.get('phone', '')
    balance = data.get('balance', 1000)
    is_admin = data.get('is_admin', 0)
    
    if not admin_id or not telegram_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    admin_user = get_user(int(admin_id))
    if not admin_user or not admin_user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    try:
        c.execute('''INSERT INTO users 
                     (telegram_id, username, first_name, phone_number, balance, is_admin) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (telegram_id, username, first_name, phone, balance, is_admin))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    finally:
        conn.close()
    
    if success:
        log_admin_action(admin_user['id'], 'add_user', f'{telegram_id} - {first_name}')
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'User already exists'})

@application.route('/api/admin/delete-user', methods=['POST'])
def delete_user():
    """Delete a user"""
    data = request.json
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    
    if not admin_id or not target_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    admin_user = get_user(int(admin_id))
    if not admin_user or not admin_user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Don't allow deleting yourself
    if int(admin_id) == int(target_id):
        return jsonify({'success': False, 'error': 'Cannot delete yourself'}), 400
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    # Delete user's transactions first
    c.execute("DELETE FROM transactions WHERE user_id IN (SELECT id FROM users WHERE telegram_id = ?)", (target_id,))
    # Delete user's purchased cards
    c.execute("DELETE FROM purchased_cards WHERE user_id IN (SELECT id FROM users WHERE telegram_id = ?)", (target_id,))
    # Delete user
    c.execute("DELETE FROM users WHERE telegram_id = ?", (target_id,))
    
    deleted = c.rowcount
    conn.commit()
    conn.close()
    
    if deleted:
        log_admin_action(admin_user['id'], 'delete_user', f'{target_id}')
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'User not found'})

@application.route('/api/admin/start-game', methods=['POST'])
def admin_start_game():
    """Start a new game session"""
    data = request.json
    admin_id = data.get('admin_id')
    
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    settings = get_game_settings()
    session_id = create_game_session(settings)
    
    log_admin_action(user['id'], 'start_game', session_id)
    
    return jsonify({'success': True, 'session_id': session_id})

@application.route('/api/admin/end-game', methods=['POST'])
def admin_end_game():
    """End current game session"""
    data = request.json
    admin_id = data.get('admin_id')
    session_id = data.get('session_id')
    winner_id = data.get('winner_id')
    winning_card = data.get('winning_card')
    
    if not admin_id or not session_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    end_game_session(session_id, winner_id, winning_card)
    
    log_admin_action(user['id'], 'end_game', f'Session {session_id} - Winner: {winner_id}')
    
    return jsonify({'success': True})

@application.route('/api/admin/logs')
def admin_logs():
    """Get admin action logs"""
    admin_id = request.args.get('admin_id')
    
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''SELECT l.created_at, u.username, l.action, l.details 
                 FROM admin_logs l
                 JOIN users u ON l.admin_id = u.id
                 ORDER BY l.created_at DESC LIMIT 50''')
    logs = c.fetchall()
    conn.close()
    
    result = []
    for l in logs:
        result.append({
            'time': l[0],
            'admin': l[1],
            'action': l[2],
            'details': l[3]
        })
    
    return jsonify({'success': True, 'logs': result})

@application.route('/api/admin/house-history')
def house_fee_history():
    """Get house fee history"""
    admin_id = request.args.get('admin_id')
    
    if not admin_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    user = get_user(int(admin_id))
    if not user or not user['is_admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''SELECT session_id, total_prize, fee_percentage, house_amount, players_prize, game_date 
                 FROM house_fee_history ORDER BY game_date DESC LIMIT 20''')
    history = c.fetchall()
    conn.close()
    
    result = []
    for h in history:
        result.append({
            'session_id': h[0],
            'total_prize': h[1],
            'fee_percentage': h[2],
            'house_amount': h[3],
            'players_prize': h[4],
            'game_date': h[5]
        })
    
    return jsonify({'success': True, 'history': result})

# Health check
@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot_process': bot_process.is_alive() if bot_process else False,
        'is_main_process': IS_MAIN_PROCESS,
        'admin_id': ADMIN_ID,
        'admin_configured': ADMIN_ID != 0,
        'url': APP_URL
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)