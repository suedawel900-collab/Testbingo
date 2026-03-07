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

# Create Flask app
app = Flask(__name__)

# Configuration from environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

# Validate required environment variables
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")
    raise ValueError("BOT_TOKEN environment variable is required")

if not ADMIN_ID:
    logger.error("ADMIN_ID environment variable is not set!")
    raise ValueError("ADMIN_ID environment variable is required")

logger.info(f"Starting application with BOT_TOKEN: {BOT_TOKEN[:5]}... and ADMIN_ID: {ADMIN_ID}")

# Initialize bot
bot = Bot(token=BOT_TOKEN)

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
        raise
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
        c.execute("INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
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

def add_transaction(user_id, tx_id, amount):
    """Add new transaction"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
        c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
                  (user_id, tx_id, amount, receipt_url))
        conn.commit()
        logger.info(f"Transaction added: {tx_id} for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding transaction {tx_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def approve_transaction(tx_id, admin_id):
    """Approve transaction and update user balance"""
    conn = None
    try:
        conn = sqlite3.connect('database/bingo.db')
        c = conn.cursor()
        
        # Update transaction status
        c.execute('''UPDATE transactions 
                     SET status = 'approved', approved_by = ?, approved_at = ? 
                     WHERE tx_id = ?''', 
                  (admin_id, datetime.now(), tx_id))
        
        # Get user_id and amount
        c.execute("SELECT user_id, amount FROM transactions WHERE tx_id = ?", (tx_id,))
        result = c.fetchone()
        if not result:
            logger.error(f"Transaction {tx_id} not found")
            return None, None
            
        user_id, amount = result
        
        # Update user balance
        c.execute("UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE id = ?",
                  (amount, amount, user_id))
        
        # Get telegram_id
        c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
        telegram_id = c.fetchone()[0]
        
        conn.commit()
        logger.info(f"Transaction approved: {tx_id}")
        return telegram_id, amount
    except Exception as e:
        logger.error(f"Error approving transaction {tx_id}: {e}")
        return None, None
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

# ==================== TELEGRAM BOT HANDLERS ====================
user_states = {}  # Track user state

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        telegram_id = user.id
        
        logger.info(f"Start command from user {telegram_id} (@{user.username})")
        
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
            f"🏆 Total Wins: *{db_user['wins']} ETB*\n\n"
            f"👇 Click PLAY BINGO to start playing!"
        )
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again later.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        logger.info(f"Button callback from user {user.id}: {data}")
        
        if data == "deposit":
            keyboard = [
                [InlineKeyboardButton("💰 START DEPOSIT", callback_data="start_deposit")],
                [InlineKeyboardButton("📋 CHECK STATUS", callback_data="check_deposit")],
                [InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                "💳 *DEPOSIT MENU*\n\n"
                "1️⃣ Send money via Telebirr to:\n"
                "   📱 *+251 91 234 5678*\n"
                "   👤 *MK BINGO*\n\n"
                "2️⃣ Click START DEPOSIT\n"
                "3️⃣ Send your Transaction ID\n\n"
                "⚠️ Minimum deposit: *50 ETB*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data == "start_deposit":
            await query.edit_message_text(
                "💰 *SEND TRANSACTION ID*\n\n"
                "Please send the Transaction ID you received from Telebirr.\n\n"
                "📝 *Example:*\n`DC39E2J9ZP`",
                parse_mode='Markdown'
            )
            user_states[user.id] = 'awaiting_tx'
        
        elif data.startswith("approve_"):
            if user.id != ADMIN_ID:
                await query.edit_message_text("❌ You are not authorized to approve deposits.")
                return
                
            tx_id = data.replace("approve_", "")
            
            # Approve transaction
            telegram_id, amount = approve_transaction(tx_id, ADMIN_ID)
            
            if telegram_id and amount:
                # Notify user
                await context.bot.send_message(
                    telegram_id,
                    f"✅ *DEPOSIT APPROVED!*\n\n"
                    f"Amount: *{amount} ETB*\n"
                    f"Transaction ID: `{tx_id}`",
                    parse_mode='Markdown'
                )
                
                await query.edit_message_text(
                    f"✅ *Deposit Approved*\n\nAmount: {amount} ETB",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Error approving transaction.")
        
        elif data.startswith("reject_"):
            if user.id != ADMIN_ID:
                await query.edit_message_text("❌ You are not authorized.")
                return
                
            tx_id = data.replace("reject_", "")
            await query.edit_message_text(f"❌ *Deposit Rejected*\n\nTransaction: {tx_id}", parse_mode='Markdown')
        
        elif data == "stats":
            db_user = get_user(user.id)
            if db_user:
                stats = (
                    f"📊 *YOUR STATS*\n\n"
                    f"💰 Balance: *{db_user['balance']} ETB*\n"
                    f"🎮 Games Played: *{db_user['games_played']}*\n"
                    f"🏆 Total Wins: *{db_user['wins']} ETB*\n"
                    f"💳 Total Deposits: *{db_user['total_deposits']} ETB*"
                )
            else:
                stats = "❌ User not found."
            await query.edit_message_text(stats, parse_mode='Markdown')
        
        elif data == "balance":
            db_user = get_user(user.id)
            if db_user:
                await query.edit_message_text(
                    f"💳 *YOUR BALANCE*\n\n"
                    f"Available: *{db_user['balance']} ETB*",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ User not found.")
        
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
                "• X Shape - X pattern"
            )
            await query.edit_message_text(help_text, parse_mode='Markdown')
        
        elif data == "main_menu":
            db_user = get_user(user.id)
            if db_user:
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
                    f"🎰 *WELCOME BACK!*\n\n💰 Balance: *{db_user['balance']} ETB*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
        
        elif data == "check_deposit":
            # Show user's recent transactions
            await query.edit_message_text(
                "📋 *Transaction History*\n\nFeature coming soon!",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logger.error(f"Error in button callback: {e}")
        await query.edit_message_text("❌ An error occurred. Please try again.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    try:
        user = update.effective_user
        text = update.message.text.strip()
        
        logger.info(f"Message from user {user.id}: {text[:50]}...")
        
        if user.id in user_states:
            if user_states[user.id] == 'awaiting_tx':
                tx_id = text.upper()
                
                # Validate transaction ID (simple validation)
                if len(tx_id) < 5:
                    await update.message.reply_text(
                        "❌ *Invalid Transaction ID*\n\nPlease check and try again.",
                        parse_mode='Markdown'
                    )
                    return
                
                # Store TX ID and ask for amount
                user_states[user.id] = ('awaiting_amount', tx_id)
                await update.message.reply_text(
                    "💰 *ENTER AMOUNT*\n\nPlease enter the amount you sent (in ETB):",
                    parse_mode='Markdown'
                )
            
            elif isinstance(user_states[user.id], tuple) and user_states[user.id][0] == 'awaiting_amount':
                try:
                    amount = int(text)
                    if amount < 50:
                        await update.message.reply_text("❌ Minimum deposit is 50 ETB")
                        return
                    
                    tx_id = user_states[user.id][1]
                    db_user = get_user(user.id)
                    
                    if not db_user:
                        await update.message.reply_text("❌ User not found. Please use /start first.")
                        return
                    
                    # Save transaction
                    if add_transaction(db_user['id'], tx_id, amount):
                        
                        # Notify admin
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
                            f"💳 Amount: *{amount} ETB*\n"
                            f"🔑 TX ID: `{tx_id}`\n\n"
                            f"[View Receipt]({receipt_url})",
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
                        await update.message.reply_text(
                            f"✅ *DEPOSIT REQUEST SENT!*\n\n"
                            f"Amount: *{amount} ETB*\n"
                            f"Transaction ID: `{tx_id}`\n\n"
                            f"Admin will approve within 5 minutes.",
                            parse_mode='Markdown'
                        )
                    else:
                        await update.message.reply_text("❌ Error saving transaction. Please try again.")
                    
                    # Clear user state
                    del user_states[user.id]
                    
                except ValueError:
                    await update.message.reply_text("❌ Please enter a valid number")
        else:
            await update.message.reply_text("Use /start to see available commands")
            
    except Exception as e:
        logger.error(f"Error in message handler: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")

# ==================== SETUP BOT ====================
def setup_bot():
    """Setup bot application"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("Bot handlers registered successfully")
        return application
    except Exception as e:
        logger.error(f"Error setting up bot: {e}")
        return None

def run_bot():
    """Run bot in separate thread"""
    try:
        application = setup_bot()
        if application:
            logger.info("Starting bot polling...")
            application.run_polling()
        else:
            logger.error("Failed to setup bot")
    except Exception as e:
        logger.error(f"Error running bot: {e}")

# Start bot in background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
logger.info("Bot thread started")

# ==================== FLASK ROUTES ====================
@app.route('/')
def index():
    """Main page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return "Error loading page", 500

@app.route('/game')
def game():
    """Serve game page"""
    try:
        user_id = request.args.get('user')
        if user_id:
            user = get_user(int(user_id))
            if user:
                return render_template('index.html', 
                                     user_id=user_id,
                                     balance=user['balance'],
                                     username=user['first_name'])
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error in game route: {e}")
        return "Error loading game", 500

@app.route('/api/user/<int:telegram_id>')
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

@app.route('/api/game/result', methods=['POST'])
def game_result():
    """Receive game results"""
    try:
        data = request.json
        telegram_id = data.get('user_id')
        result = data.get('result', {})
        
        if not telegram_id:
            return jsonify({'success': False, 'error': 'Missing user_id'}), 400
        
        user = get_user(telegram_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        # Update balance (subtract payment)
        new_balance = update_balance(telegram_id, result.get('amount_paid', 0), 'subtract')
        
        # If won, add prize to balance
        if result.get('won'):
            new_balance = update_balance(telegram_id, result['prize'], 'add')
            
            # Send notification via bot
            asyncio.run_coroutine_threadsafe(
                bot.send_message(
                    chat_id=telegram_id,
                    text=f"🎉 *CONGRATULATIONS!*\n\nYou won *{result['prize']} ETB*!",
                    parse_mode='Markdown'
                ),
                asyncio.new_event_loop()
            )
        
        return jsonify({'success': True, 'new_balance': new_balance})
        
    except Exception as e:
        logger.error(f"Error in game result: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

@app.route('/api/game/settings')
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

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'bot_token_configured': bool(BOT_TOKEN),
        'admin_id_configured': bool(ADMIN_ID)
    })

# ==================== MAIN ENTRY POINT ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)