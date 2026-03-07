import os
import sqlite3
import multiprocessing
import logging
import time
import sys
from datetime import datetime
from flask import Flask, request, jsonify, render_template

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
application = Flask(__name__)
app = application

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
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
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
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

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
            'phone_number': user[8],
            'created_at': user[9]
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
    user_id, amount = c.fetchone()
    
    c.execute("UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE id = ?",
              (amount, amount, user_id))
    
    c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
    telegram_id = c.fetchone()[0]
    
    conn.commit()
    conn.close()
    return telegram_id, amount

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
        logger.info(f"Start from {user.first_name}")
        
        # Get or create user
        db_user = bot_get_user(user.id)
        if not db_user:
            bot_create_user(user.id, user.username, user.first_name)
            db_user = bot_get_user(user.id)
        
        # Check if phone number exists
        if not db_user[8]:  # phone_number column
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
        
        # Main menu
        keyboard = [
            [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
            [
                InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
                InlineKeyboardButton("📊 STATS", callback_data="stats")
            ],
            [InlineKeyboardButton("💳 BALANCE", callback_data="balance")]
        ]
        
        await update.message.reply_text(
            f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
            f"💰 Balance: {db_user[4]} ETB",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        user = update.effective_user
        
        if contact and contact.user_id == user.id:
            bot_update_phone(user.id, contact.phone_number)
            await update.message.reply_text(f"✅ Phone number saved!")
            
            # Show main menu
            db_user = bot_get_user(user.id)
            keyboard = [
                [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
                [
                    InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
                    InlineKeyboardButton("📊 STATS", callback_data="stats")
                ],
                [InlineKeyboardButton("💳 BALANCE", callback_data="balance")]
            ]
            
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
            await query.edit_message_text(
                f"💳 *Your Balance*\n\n"
                f"Available: *{db_user[4]} ETB*\n"
                f"Total Deposits: *{db_user[7]} ETB*",
                parse_mode='Markdown'
            )
        
        elif data == "stats":
            db_user = bot_get_user(user.id)
            await query.edit_message_text(
                f"📊 *Your Stats*\n\n"
                f"Balance: *{db_user[4]} ETB*\n"
                f"Games Played: *{db_user[5]}*\n"
                f"Wins: *{db_user[6]} ETB*",
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
            user_id, amount = c.fetchone()
            c.execute("UPDATE users SET balance=balance+?, total_deposits=total_deposits+? WHERE id=?", 
                     (amount, amount, user_id))
            c.execute("SELECT telegram_id FROM users WHERE id=?", (user_id,))
            telegram_id = c.fetchone()[0]
            conn.commit()
            conn.close()
            
            await context.bot.send_message(
                telegram_id, 
                f"✅ *Deposit Approved!*\n\n"
                f"Amount: *{amount} ETB*\n"
                f"Transaction ID: `{tx_id}`",
                parse_mode='Markdown'
            )
            
            await query.edit_message_text(
                f"✅ *Deposit Approved*\n\n"
                f"Amount: {amount} ETB",
                parse_mode='Markdown'
            )
    
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
    
    # Create and run application with proper error handling
    try:
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CallbackQueryHandler(button_handler))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("Bot process starting polling...")
        
        # Run with error handling for conflicts
        bot_app.run_polling(drop_pending_updates=True)
        
    except Conflict as e:
        logger.error(f"Conflict error - another bot instance is running: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Bot process error: {e}")
        time.sleep(5)

# ==================== START BOT PROCESS (ONLY ONCE) ====================
bot_process = None

def start_bot_process():
    """Start the bot in a separate process - ONLY ONCE"""
    global bot_process
    
    # Only start bot in the main process, not in Gunicorn workers
    if not IS_MAIN_PROCESS:
        logger.info("Skipping bot start in Gunicorn worker")
        return
    
    # Check if already running
    if bot_process and bot_process.is_alive():
        logger.info("Bot process already running")
        return
    
    # Kill any existing bot processes
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'] and 'bot' in str(proc.info['cmdline']).lower():
                    if proc.info['pid'] != current_pid:
                        logger.info(f"Killing old bot process: {proc.info['pid']}")
                        proc.kill()
            except:
                pass
    except:
        pass
    
    # Start new bot process
    bot_process = multiprocessing.Process(target=run_bot_process, daemon=True)
    bot_process.start()
    logger.info(f"Bot process started with PID: {bot_process.pid}")

# Start bot ONLY in main process
if BOT_TOKEN and IS_MAIN_PROCESS:
    start_bot_process()
else:
    logger.info("Bot not started - not main process or no token")

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
            'balance': user['balance']
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@application.route('/api/game/session')
def get_game_session():
    return jsonify({
        'success': True,
        'total_cards_sold': 0,
        'total_players': 0,
        'prize_pool': 0,
        'status': 'waiting'
    })

@application.route('/api/game/purchase', methods=['POST'])
def purchase_cards():
    data = request.json
    return jsonify({
        'success': True,
        'new_balance': 1000,
        'game_ready': False
    })

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot_process': bot_process.is_alive() if bot_process else False,
        'is_main_process': IS_MAIN_PROCESS,
        'url': APP_URL
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)