import os
import json
import sqlite3
import hashlib
import hmac
import asyncio
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import logging

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration from environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'your-secret-key')

# Initialize bot
bot = Bot(token=BOT_TOKEN)

# Database setup
def init_db():
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
    
    # Active games table
    c.execute('''CREATE TABLE IF NOT EXISTS active_games
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_round TEXT UNIQUE,
                  game_type TEXT,
                  card_price INTEGER,
                  prize_pool INTEGER,
                  status TEXT DEFAULT 'waiting',
                  started_at TIMESTAMP,
                  ended_at TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

# Initialize database
init_db()

# Database helper functions
def get_user(telegram_id):
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
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
              (telegram_id, username, first_name))
    conn.commit()
    conn.close()
    logger.info(f"New user created: {username} ({telegram_id})")

def update_balance(telegram_id, amount, add=True):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    if add:
        c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
    else:
        c.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (amount, telegram_id))
    conn.commit()
    
    # Get new balance
    c.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,))
    new_balance = c.fetchone()[0]
    conn.close()
    return new_balance

def add_transaction(user_id, tx_id, amount):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
              (user_id, tx_id, amount, receipt_url))
    conn.commit()
    conn.close()
    logger.info(f"Transaction added: {tx_id} for user {user_id}")

def approve_transaction(tx_id, admin_id):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''UPDATE transactions 
                 SET status = 'approved', approved_by = ?, approved_at = ? 
                 WHERE tx_id = ?''', 
              (admin_id, datetime.now(), tx_id))
    
    # Get user_id and amount
    c.execute("SELECT user_id, amount FROM transactions WHERE tx_id = ?", (tx_id,))
    user_id, amount = c.fetchone()
    
    # Update user balance
    c.execute("UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE id = ?",
              (amount, amount, user_id))
    
    conn.commit()
    conn.close()
    logger.info(f"Transaction approved: {tx_id}")
    return user_id, amount

def reject_transaction(tx_id):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("UPDATE transactions SET status = 'rejected' WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()
    logger.info(f"Transaction rejected: {tx_id}")

def get_pending_transactions():
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE status = 'pending'")
    transactions = c.fetchall()
    conn.close()
    return transactions

def add_game_history(user_id, game_type, cards_bought, amount_paid, won=False, prize=0):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    c.execute('''INSERT INTO game_history 
                 (user_id, game_type, cards_bought, amount_paid, won, prize)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, game_type, cards_bought, amount_paid, won, prize))
    
    if won:
        c.execute("UPDATE users SET games_played = games_played + 1, wins = wins + ? WHERE id = ?",
                  (prize, user_id))
    else:
        c.execute("UPDATE users SET games_played = games_played + 1 WHERE id = ?", (user_id,))
    
    conn.commit()
    conn.close()

# Telegram Bot Handlers
pending_transactions = {}  # Temporary storage for pending approvals

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
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
        )],
        [
            InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
            InlineKeyboardButton("📊 STATS", callback_data="stats")
        ],
        [
            InlineKeyboardButton("💳 BALANCE", callback_data="balance"),
            InlineKeyboardButton("❓ HELP", callback_data="help")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        f"🎰 *WELCOME TO MK BINGO, {user.first_name}!*\n\n"
        f"💰 Current Balance: *{db_user['balance']} ETB*\n"
        f"🎮 Games Played: *{db_user['games_played']}*\n"
        f"🏆 Total Wins: *{db_user['wins']} ETB*\n"
        f"💳 Total Deposits: *{db_user['total_deposits']} ETB*\n\n"
        f"👇 Click PLAY BINGO to start playing!"
    )
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /deposit command"""
    keyboard = [
        [InlineKeyboardButton("💰 DEPOSIT VIA TELEBIRR", callback_data="start_deposit")],
        [InlineKeyboardButton("📋 CHECK STATUS", callback_data="check_deposit")]
    ]
    
    message = (
        "💳 *DEPOSIT INSTRUCTIONS*\n\n"
        "1️⃣ Send money via Telebirr to:\n"
        "   📱 *+251 91 234 5678*\n"
        "   👤 *MK BINGO OFFICIAL*\n\n"
        "2️⃣ After payment, click DEPOSIT button\n"
        "3️⃣ Send your Transaction ID\n"
        "4️⃣ Admin will approve within 5 minutes\n\n"
        "⚠️ *Minimum deposit: 50 ETB*"
    )
    
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "deposit":
        keyboard = [
            [InlineKeyboardButton("💰 START DEPOSIT", callback_data="start_deposit")],
            [InlineKeyboardButton("📋 CHECK STATUS", callback_data="check_deposit")],
            [InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "💳 *Deposit Menu*\n\nChoose an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "start_deposit":
        await query.edit_message_text(
            "💰 *SEND YOUR TRANSACTION ID*\n\n"
            "Please send the Transaction ID you received from Telebirr.\n\n"
            "📝 *Example:*\n`DC39E2J9ZP`\n\n"
            "I'll forward it to admin for approval.",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_tx'] = True
    
    elif data.startswith("approve_"):
        tx_id = data.replace("approve_", "")
        
        # Approve transaction
        user_id, amount = approve_transaction(tx_id, ADMIN_ID)
        
        # Get user's telegram_id
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
        telegram_id = c.fetchone()[0]
        conn.close()
        
        # Notify user
        await context.bot.send_message(
            telegram_id,
            f"✅ *DEPOSIT APPROVED!*\n\n"
            f"Amount: *{amount} ETB*\n"
            f"Transaction ID: `{tx_id}`\n\n"
            f"Your balance has been updated!",
            parse_mode='Markdown'
        )
        
        await query.edit_message_text(
            f"✅ *Deposit Approved*\n\n"
            f"User ID: {user_id}\n"
            f"Amount: {amount} ETB\n"
            f"Transaction: {tx_id}",
            parse_mode='Markdown'
        )
    
    elif data.startswith("reject_"):
        tx_id = data.replace("reject_", "")
        
        # Reject transaction
        reject_transaction(tx_id)
        
        # Get user_id
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM transactions WHERE tx_id = ?", (tx_id,))
        user_id = c.fetchone()[0]
        c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
        telegram_id = c.fetchone()[0]
        conn.close()
        
        # Notify user
        await context.bot.send_message(
            telegram_id,
            f"❌ *DEPOSIT REJECTED*\n\n"
            f"Transaction ID: `{tx_id}`\n\n"
            f"Please check your payment and try again, or contact support.",
            parse_mode='Markdown'
        )
        
        await query.edit_message_text(
            f"❌ *Deposit Rejected*\n\nTransaction: {tx_id}",
            parse_mode='Markdown'
        )
    
    elif data == "stats":
        db_user = get_user(user.id)
        stats = (
            f"📊 *YOUR STATS*\n\n"
            f"💰 Balance: *{db_user['balance']} ETB*\n"
            f"🎮 Games Played: *{db_user['games_played']}*\n"
            f"🏆 Total Wins: *{db_user['wins']} ETB*\n"
            f"💳 Total Deposits: *{db_user['total_deposits']} ETB*\n"
            f"📅 Member Since: *{db_user['created_at'][:10]}*"
        )
        await query.edit_message_text(stats, parse_mode='Markdown')
    
    elif data == "balance":
        db_user = get_user(user.id)
        await query.edit_message_text(
            f"💳 *YOUR BALANCE*\n\n"
            f"Available: *{db_user['balance']} ETB*\n\n"
            f"Use /deposit to add funds.",
            parse_mode='Markdown'
        )
    
    elif data == "help":
        help_text = (
            "❓ *HOW TO PLAY*\n\n"
            "1️⃣ *Deposit* - Add funds via Telebirr\n"
            "2️⃣ *Select Cards* - Choose 1-1000 cards\n"
            "3️⃣ *Pay* - Confirm your selection\n"
            "4️⃣ *Play* - Numbers are called automatically\n"
            "5️⃣ *Win* - Click BINGO when you win!\n\n"
            "🏆 *WIN TYPES*\n"
            "• Full House - All numbers\n"
            "• 1 Row - Complete any row\n"
            "• 1 Column - Complete any column\n"
            "• 4 Corners - All corners\n"
            "• X Shape - X pattern\n\n"
            "💰 *PRIZES*\n"
            "Prizes are shared equally among winners"
        )
        await query.edit_message_text(help_text, parse_mode='Markdown')
    
    elif data == "check_deposit":
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        c.execute('''SELECT t.tx_id, t.amount, t.status, t.created_at 
                     FROM transactions t 
                     JOIN users u ON t.user_id = u.id 
                     WHERE u.telegram_id = ? 
                     ORDER BY t.created_at DESC LIMIT 5''', (user.id,))
        transactions = c.fetchall()
        conn.close()
        
        if transactions:
            msg = "📋 *RECENT TRANSACTIONS*\n\n"
            for tx in transactions:
                status_emoji = "✅" if tx[2] == 'approved' else "⏳" if tx[2] == 'pending' else "❌"
                msg += f"{status_emoji} TX: `{tx[0]}`\n"
                msg += f"   Amount: {tx[1]} ETB\n"
                msg += f"   Status: {tx[2].upper()}\n"
                msg += f"   Date: {tx[3][:16]}\n\n"
        else:
            msg = "📋 No transactions found."
        
        await query.edit_message_text(msg, parse_mode='Markdown')
    
    elif data == "main_menu":
        db_user = get_user(user.id)
        keyboard = [
            [InlineKeyboardButton(
                "🎮 PLAY BINGO",
                web_app={"url": f"{APP_URL}/game?user={user.id}"}
            )],
            [
                InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
                InlineKeyboardButton("📊 STATS", callback_data="stats")
            ],
            [
                InlineKeyboardButton("💳 BALANCE", callback_data="balance"),
                InlineKeyboardButton("❓ HELP", callback_data="help")
            ]
        ]
        
        await query.edit_message_text(
            f"🎰 *WELCOME BACK!*\n\n"
            f"💰 Balance: *{db_user['balance']} ETB*\n\n"
            f"👇 Choose an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (Transaction IDs)"""
    if context.user_data.get('awaiting_tx'):
        tx_id = update.message.text.strip().upper()
        user = update.effective_user
        
        # Validate transaction ID format
        if len(tx_id) != 10 or not tx_id.isalnum():
            await update.message.reply_text(
                "❌ *Invalid Transaction ID*\n\n"
                "Please check and try again.\n"
                "Format: `DC39E2J9ZP` (10 characters)",
                parse_mode='Markdown'
            )
            return
        
        # Ask for amount
        await update.message.reply_text(
            "💰 *ENTER AMOUNT*\n\n"
            "Please enter the amount you sent (in ETB):",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_tx'] = False
        context.user_data['temp_tx'] = tx_id
        context.user_data['awaiting_amount'] = True
    
    elif context.user_data.get('awaiting_amount'):
        try:
            amount = int(update.message.text.strip())
            if amount < 50:
                await update.message.reply_text("❌ Minimum deposit is 50 ETB")
                return
            
            tx_id = context.user_data['temp_tx']
            user = update.effective_user
            
            # Get user from database
            db_user = get_user(user.id)
            
            # Save transaction
            add_transaction(db_user['id'], tx_id, amount)
            
            # Create admin notification
            keyboard = [
                [
                    InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_{tx_id}"),
                    InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{tx_id}")
                ]
            ]
            
            receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
            
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 *NEW DEPOSIT REQUEST*\n\n"
                f"👤 User: @{user.username or 'No username'}\n"
                f"🆔 ID: {user.id}\n"
                f"📝 Name: {user.first_name}\n"
                f"💳 Amount: *{amount} ETB*\n"
                f"🔑 TX ID: `{tx_id}`\n\n"
                f"🔗 [View Receipt]({receipt_url})",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            await update.message.reply_text(
                f"✅ *DEPOSIT REQUEST SENT!*\n\n"
                f"Amount: *{amount} ETB*\n"
                f"Transaction ID: `{tx_id}`\n\n"
                f"Admin will approve within 5 minutes.\n"
                f"You'll be notified when approved.",
                parse_mode='Markdown'
            )
            
            # Clear user data
            context.user_data.clear()
            
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number")
    
    else:
        await update.message.reply_text(
            "Use /start to see available commands"
        )

# Setup bot application
def setup_bot():
    """Setup and return bot application"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    return application

# Run bot in separate thread
def run_bot():
    """Run bot in a separate thread"""
    application = setup_bot()
    logger.info("Starting bot polling...")
    application.run_polling()

# Start bot in background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

# Flask routes
@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/game')
def game():
    """Serve game page with user data"""
    user_id = request.args.get('user')
    if user_id:
        user = get_user(user_id)
        if user:
            return render_template('index.html', 
                                 user_id=user_id,
                                 balance=user['balance'],
                                 username=user['first_name'])
    return render_template('index.html')

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

@app.route('/api/game/result', methods=['POST'])
def game_result():
    """Receive game results from frontend"""
    data = request.json
    telegram_id = data.get('user_id')
    result = data.get('result', {})
    
    user = get_user(telegram_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Update balance
    new_balance = result.get('new_balance', user['balance'])
    update_balance(telegram_id, new_balance, add=False)
    
    # Save game history
    add_game_history(
        user['id'],
        result.get('game_type', 'unknown'),
        result.get('cards_bought', 0),
        result.get('amount_paid', 0),
        result.get('won', False),
        result.get('prize', 0)
    )
    
    # Send notification to user if they won
    if result.get('won'):
        asyncio.run_coroutine_threadsafe(
            bot.send_message(
                chat_id=telegram_id,
                text=f"🎉 *CONGRATULATIONS!*\n\nYou won *{result['prize']} ETB*!\nNew balance: *{new_balance} ETB*",
                parse_mode='Markdown'
            ),
            asyncio.new_event_loop()
        )
    
    return jsonify({'success': True})

@app.route('/api/game/current')
def current_game():
    """Get current active game settings"""
    # For now, return default settings
    return jsonify({
        'success': True,
        'game_type': 'full house',
        'card_price': 10,
        'prize_pool': 2000
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)