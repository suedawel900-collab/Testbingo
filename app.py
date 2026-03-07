import os
import sqlite3
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== FLASK APP ====================
application = Flask(__name__)  # CRITICAL: Named 'application' for Gunicorn
app = application

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

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
                  balance INTEGER DEFAULT 0,
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
            'created_at': user[8]
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
    logger.info(f"User created: {username} ({telegram_id})")

def add_transaction(user_id, tx_id, amount):
    """Add new transaction"""
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
              (user_id, tx_id, amount, receipt_url))
    conn.commit()
    conn.close()
    logger.info(f"Transaction added: {tx_id}")

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
    logger.info(f"Transaction approved: {tx_id}")
    return telegram_id, amount

# ==================== TELEGRAM BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    if not get_user(user.id):
        create_user(user.id, user.username, user.first_name)
    
    db_user = get_user(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
        [
            InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
            InlineKeyboardButton("📊 STATS", callback_data="stats")
        ]
    ]
    
    await update.message.reply_text(
        f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
        f"💰 Balance: {db_user['balance']} ETB",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    
    if data == "deposit":
        await query.edit_message_text(
            "💰 Send your Telebirr Transaction ID:"
        )
        context.user_data['awaiting_tx'] = True
    
    elif data == "stats":
        db_user = get_user(user.id)
        await query.edit_message_text(
            f"📊 Your Stats:\n"
            f"Balance: {db_user['balance']} ETB\n"
            f"Games: {db_user['games_played']}\n"
            f"Wins: {db_user['wins']} ETB"
        )
    
    elif data.startswith("approve_"):
        if user.id != ADMIN_ID:
            await query.edit_message_text("❌ Unauthorized")
            return
        
        tx_id = data.replace("approve_", "")
        telegram_id, amount = approve_transaction(tx_id, ADMIN_ID)
        
        await context.bot.send_message(
            telegram_id,
            f"✅ Deposit of {amount} ETB approved!"
        )
        await query.edit_message_text("✅ Approved")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (Transaction IDs)"""
    if context.user_data.get('awaiting_tx'):
        tx_id = update.message.text.strip().upper()
        user = update.effective_user
        
        db_user = get_user(user.id)
        
        # Ask for amount
        await update.message.reply_text("💰 Enter amount:")
        context.user_data['awaiting_tx'] = False
        context.user_data['temp_tx'] = tx_id
        context.user_data['awaiting_amount'] = True
    
    elif context.user_data.get('awaiting_amount'):
        try:
            amount = int(update.message.text.strip())
            tx_id = context.user_data['temp_tx']
            user = update.effective_user
            
            db_user = get_user(user.id)
            add_transaction(db_user['id'], tx_id, amount)
            
            # Notify admin
            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}")
            ]]
            
            await context.bot.send_message(
                ADMIN_ID,
                f"Deposit from @{user.username}\n"
                f"Amount: {amount} ETB\n"
                f"TX: {tx_id}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            await update.message.reply_text("Deposit request sent to admin.")
            context.user_data.clear()
            
        except ValueError:
            await update.message.reply_text("❌ Invalid amount")

# ==================== BOT SETUP ====================
def run_bot():
    """Run bot in a separate thread"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    try:
        # Create application
        bot_app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(CallbackQueryHandler(button_handler))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("Starting bot polling...")
        
        # Run polling (this blocks the thread)
        bot_app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Bot error: {e}")

# Start bot in a background thread
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
            'balance': user['balance']
        })
    return jsonify({'success': False, 'error': 'Not found'}), 404

@application.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'bot': 'running' if BOT_TOKEN else 'no token'
    })

# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    application.run(host='0.0.0.0', port=port)