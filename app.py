import os
import sqlite3
import threading
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
                  total_cards INTEGER,
                  card_price INTEGER,
                  total_prize INTEGER,
                  fee_percentage REAL,
                  house_amount INTEGER,
                  players_prize INTEGER,
                  winner_count INTEGER,
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
    c.execute("SELECT game_type, card_price, min_cards_to_start, call_interval, house_fee FROM game_settings ORDER BY updated_at DESC LIMIT 1")
    settings = c.fetchone()
    conn.close()
    
    if settings:
        return {
            'game_type': settings[0],
            'card_price': settings[1],
            'min_cards_to_start': settings[2],
            'call_interval': settings[3],
            'house_fee': settings[4]
        }
    return {'game_type': 'full house', 'card_price': 10, 
            'min_cards_to_start': 10, 'call_interval': 3, 'house_fee': 5}

def update_game_settings(admin_id, settings):
    """Update game settings"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''INSERT INTO game_settings 
                 (game_type, card_price, min_cards_to_start, call_interval, house_fee, updated_by) 
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (settings['game_type'], settings['card_price'], 
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
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*), SUM(amount) FROM transactions WHERE status = 'approved'")
    row = c.fetchone()
    tx_count = row[0] or 0
    tx_total = row[1] or 0
    
    c.execute("SELECT SUM(games_played) FROM users")
    total_games = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM game_sessions WHERE status = 'active'")
    active_games = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
    pending_count = c.fetchone()[0]
    
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
                 (session_id, game_type, card_price, status, house_fee) 
                 VALUES (?, ?, ?, 'waiting', ?)''',
              (session_id, settings['game_type'], settings['card_price'], 
               settings.get('house_fee', 5)))
    conn.commit()
    conn.close()
    
    return session_id

def end_game_session(session_id, winner_ids):
    """End a game session and distribute prizes"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT total_cards_sold, card_price, house_fee FROM game_sessions WHERE session_id = ?", (session_id,))
    session = c.fetchone()
    
    if session:
        total_cards, card_price, house_fee = session
        total_prize = total_cards * card_price
        house_amount = int(total_prize * house_fee / 100)
        players_prize = total_prize - house_amount
        
        winner_count = len(winner_ids)
        prize_per_winner = players_prize // winner_count if winner_count > 0 else 0
        
        c.execute('''UPDATE game_sessions 
                     SET status = 'ended', ended_at = ?, 
                         prize_pool = ?, house_collected = ?
                     WHERE session_id = ?''',
                  (datetime.now(), total_prize, house_amount, session_id))
        
        c.execute('''INSERT INTO house_fee_history 
                     (session_id, total_cards, card_price, total_prize, 
                      fee_percentage, house_amount, players_prize, winner_count) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (session_id, total_cards, card_price, total_prize, 
                   house_fee, house_amount, players_prize, winner_count))
        
        for winner_id in winner_ids:
            c.execute("SELECT id FROM users WHERE telegram_id = ?", (winner_id,))
            user_result = c.fetchone()
            if user_result:
                user_db_id = user_result[0]
                c.execute("UPDATE users SET balance = balance + ?, wins = wins + ? WHERE id = ?",
                         (prize_per_winner, prize_per_winner, user_db_id))
                
                c.execute('''UPDATE game_participants 
                             SET has_bingo = 1, prize_won = ? 
                             WHERE session_id = ? AND user_id = ?''',
                          (prize_per_winner, session_id, user_db_id))
        
        # Release cards for next round
        c.execute('''UPDATE purchased_cards 
                     SET status = 'released' 
                     WHERE session_id = ?''', (session_id,))
        
        released_count = c.rowcount
        logger.info(f"Released {released_count} cards from session {session_id}")
    
    conn.commit()
    conn.close()
    return released_count

# ==================== SIMPLE BOT WITH THREADING ====================
def run_bot():
    """Simple bot function that runs in a thread"""
    import asyncio
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
    
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    logger.info(f"Starting bot in thread...")
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"Start from {user.first_name}")
        
        # Simple response without database for now
        keyboard = [
            [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})]
        ]
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    logger.info("Bot started polling...")
    application.run_polling(drop_pending_updates=True)

# Start bot in a daemon thread
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
    purchased = {}
    my_cards = []
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT card_number, user_id FROM purchased_cards WHERE status = 'active'")
    for row in c.fetchall():
        purchased[row[0]] = row[1]
    
    user_id = request.args.get('user_id')
    if user_id:
        c.execute("SELECT card_number FROM purchased_cards WHERE user_id = ? AND status = 'active'", 
                  (get_user(int(user_id))['id'] if get_user(int(user_id)) else 0,))
        my_cards = [row[0] for row in c.fetchall()]
    
    conn.close()
    
    return jsonify({
        'success': True,
        'purchased': list(purchased.keys()),
        'purchased_by': purchased,
        'my_cards': my_cards
    })

@application.route('/api/game/session')
def get_game_session():
    """Get current game session info"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT session_id, total_cards_sold, total_players, card_price, status, house_fee FROM game_sessions WHERE status IN ('waiting', 'countdown', 'active') ORDER BY id DESC LIMIT 1")
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
            'card_price': session[3],
            'prize_pool': prize_pool,
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
    
    settings = get_game_settings()
    
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    
    c.execute("SELECT session_id FROM game_sessions WHERE status = 'waiting' ORDER BY id DESC LIMIT 1")
    session = c.fetchone()
    
    if not session:
        session_id = str(uuid.uuid4())[:8]
        c.execute('''INSERT INTO game_sessions 
                     (session_id, game_type, card_price, status, house_fee) 
                     VALUES (?, ?, ?, 'waiting', ?)''',
                  (session_id, settings['game_type'], settings['card_price'], settings['house_fee']))
    else:
        session_id = session[0]
    
    c.execute('''INSERT INTO game_participants 
                 (session_id, user_id, cards, cards_bought, paid_amount) 
                 VALUES (?, ?, ?, ?, ?)''',
              (session_id, user['id'], json.dumps(cards), len(cards), total_paid))
    
    c.execute('''UPDATE game_sessions 
                 SET total_cards_sold = total_cards_sold + ?,
                     total_players = total_players + 1
                 WHERE session_id = ?''',
              (len(cards), session_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'session_id': session_id})

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot_token_configured': bool(BOT_TOKEN),
        'url': APP_URL
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)