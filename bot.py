import os
import sqlite3
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from datetime import datetime
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
APP_URL = os.environ.get('RAILWAY_STATIC_URL', 'http://localhost:5000')

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

def add_transaction(user_id, tx_id, amount):
    conn = sqlite3.connect('database/bingo.db')
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute("INSERT INTO transactions (user_id, tx_id, amount, receipt_url) VALUES (?, ?, ?, ?)",
              (user_id, tx_id, amount, receipt_url))
    conn.commit()
    conn.close()

def approve_transaction(tx_id, admin_id):
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

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if not get_user(user.id):
        create_user(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY BINGO", web_app={"url": f"{APP_URL}/game?user={user.id}"})],
        [
            InlineKeyboardButton("💰 DEPOSIT", callback_data="deposit"),
            InlineKeyboardButton("📊 STATS", callback_data="stats")
        ]
    ]
    
    await update.message.reply_text(
        f"🎰 Welcome to MK BINGO, {user.first_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "deposit":
        await query.edit_message_text(
            "💰 Send your Telebirr Transaction ID:"
        )
        context.user_data['awaiting_tx'] = True
    
    elif data.startswith("approve_"):
        tx_id = data.replace("approve_", "")
        telegram_id, amount = approve_transaction(tx_id, ADMIN_ID)
        
        await context.bot.send_message(
            telegram_id,
            f"✅ Deposit of {amount} ETB approved!"
        )
        await query.edit_message_text("✅ Approved")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_tx'):
        tx_id = update.message.text.strip().upper()
        user = update.effective_user
        
        db_user = get_user(user.id)
        add_transaction(db_user['id'], tx_id, 0)
        
        # Notify admin
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tx_id}")
        ]]
        
        await context.bot.send_message(
            ADMIN_ID,
            f"Deposit from @{user.username}\nTX: {tx_id}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        await update.message.reply_text("Deposit request sent to admin.")
        context.user_data.clear()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()