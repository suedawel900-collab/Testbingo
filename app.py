import os
import sqlite3
import multiprocessing
import logging
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
application = Flask(__name__)  # CRITICAL: Named 'application' for Gunicorn
app = application

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
RAILWAY_URL = os.environ.get('RAILWAY_STATIC_URL', 'localhost:5000')
APP_URL = f"https://{RAILWAY_URL}"  # Add https://

logger.info(f"Starting with BOT_TOKEN: {BOT_TOKEN[:5] if BOT_TOKEN else 'None'}...")
logger.info(f"APP_URL: {APP_URL}")

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
                  tx_id TEXT UNIQUE,
                  amount INTEGER DEFAULT 0,
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

def add_transaction(user_id, tx_id, amount):
    """Add new transaction"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
              (user_id, tx_id, amount, receipt_url))
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
    
    # Bot handlers
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
            ]
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
                ]
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
        
        if data == "deposit":
            await query.edit_message_text("💰 Send your Telebirr Transaction ID:")
            context.user_data['awaiting_tx'] = True
        
        elif data == "stats":
            db_user = bot_get_user(query.from_user.id)
            await query.edit_message_text(
                f"📊 Your Stats:\n"
                f"Balance: {db_user[4]} ETB\n"
                f"Games: {db_user[5]}\n"
                f"Wins: {db_user[6]} ETB"
            )
        
        elif data.startswith("approve_"):
            if query.from_user.id != ADMIN_ID:
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
            
            await context.bot.send_message(telegram_id, f"✅ Deposit of {amount} ETB approved!")
            await query.edit_message_text("✅ Approved")
    
    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get('awaiting_tx'):
            tx_id = update.message.text.strip().upper()
            await update.message.reply_text("💰 Enter amount:")
            context.user_data['awaiting_tx'] = False
            context.user_data['temp_tx'] = tx_id
            context.user_data['awaiting_amount'] = True
        
        elif context.user_data.get('awaiting_amount'):
            try:
                amount = int(update.message.text.strip())
                tx_id = context.user_data['temp_tx']
                user = update.effective_user
                
                db_user = bot_get_user(user.id)
                
                conn = sqlite3.connect('database/bingo.db')
                c = conn.cursor()
                receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
                c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
                         (db_user[0], tx_id, amount, receipt_url))
                conn.commit()
                conn.close()
                
                # Notify admin
                keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}")]]
                
                await context.bot.send_message(
                    ADMIN_ID,
                    f"Deposit from @{user.username}\nAmount: {amount} ETB\nTX: {tx_id}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                await update.message.reply_text("Deposit request sent to admin.")
                context.user_data.clear()
                
            except ValueError:
                await update.message.reply_text("❌ Invalid amount")
    
    # Create and run application
    try:
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CallbackQueryHandler(button_handler))
        bot_app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("Bot process starting polling...")
        bot_app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Bot process error: {e}")
        time.sleep(5)  # Wait before restarting

# ==================== START BOT PROCESS ====================
bot_process = None

def start_bot_process():
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
    start_bot_process()
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
            'balance': user['balance']
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot_process': bot_process.is_alive() if bot_process else False,
        'bot_pid': bot_process.pid if bot_process else None,
        'url': APP_URL
    })

@application.route('/bot-status')
def bot_status():
    """Check and restart bot if needed"""
    global bot_process
    if not bot_process or not bot_process.is_alive():
        if BOT_TOKEN:
            start_bot_process()
            return jsonify({'status': 'restarting'})
        return jsonify({'status': 'no token'})
    return jsonify({'status': 'running', 'pid': bot_process.pid})

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)