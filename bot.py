#!/usr/bin/env python3
"""
MK BINGO - Telegram Bot Process
"""

import os
import sys
import time
import logging
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
RAILWAY_URL = os.environ.get('RAILWAY_STATIC_URL', 'localhost:5000')
APP_URL = f"https://{RAILWAY_URL}"

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable not set!")
    sys.exit(1)

logger.info("=" * 50)
logger.info(f"🚀 Starting MK BINGO Bot Process")
logger.info(f"🤖 Bot Token: {BOT_TOKEN[:5]}...")
logger.info(f"🌐 App URL: {APP_URL}")
logger.info(f"👑 Admin ID: {ADMIN_ID}")
logger.info("=" * 50)

# ==================== DATABASE FUNCTIONS ====================
def get_db_connection():
    """Get database connection"""
    return sqlite3.connect('database/bingo.db', check_same_thread=False)

def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Get user by telegram ID"""
    conn = get_db_connection()
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

def create_user(telegram_id: int, username: str, first_name: str) -> None:
    """Create new user"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
        (telegram_id, username, first_name)
    )
    conn.commit()
    conn.close()
    logger.info(f"✅ Created user: {first_name} (ID: {telegram_id})")

def update_user_phone(telegram_id: int, phone_number: str) -> None:
    """Update user's phone number"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET phone_number = ? WHERE telegram_id = ?",
        (phone_number, telegram_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"📱 Updated phone for user {telegram_id}")

def add_transaction(user_id: int, amount: int, tx_id: str) -> None:
    """Add new deposit transaction"""
    conn = get_db_connection()
    c = conn.cursor()
    receipt_url = f"https://transactioninfo.ethiotelecom.et/receipt/{tx_id}"
    c.execute(
        "INSERT INTO transactions (user_id, amount, tx_id, receipt_url) VALUES (?, ?, ?, ?)",
        (user_id, amount, tx_id, receipt_url)
    )
    conn.commit()
    conn.close()
    logger.info(f"💰 Added transaction: {tx_id} for {amount} ETB")

def approve_transaction(tx_id: str, admin_id: int) -> tuple:
    """Approve transaction and update user balance"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute(
        "UPDATE transactions SET status = 'approved', approved_by = ?, approved_at = ? WHERE tx_id = ?",
        (admin_id, datetime.now(), tx_id)
    )
    
    c.execute("SELECT user_id, amount FROM transactions WHERE tx_id = ?", (tx_id,))
    result = c.fetchone()
    if not result:
        conn.close()
        return None, None
    
    user_id, amount = result
    
    c.execute(
        "UPDATE users SET balance = balance + ?, total_deposits = total_deposits + ? WHERE id = ?",
        (amount, amount, user_id)
    )
    
    c.execute("SELECT telegram_id FROM users WHERE id = ?", (user_id,))
    telegram_id = c.fetchone()[0]
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Approved transaction {tx_id} for {amount} ETB")
    return telegram_id, amount

def get_pending_transactions_count() -> int:
    """Get count of pending transactions"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending'")
    count = c.fetchone()[0]
    conn.close()
    return count

# ==================== TELEGRAM BOT HANDLERS ====================
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.error import Conflict, TimedOut, NetworkError

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    logger.info(f"📨 Start command from {user.first_name} (ID: {user.id})")
    
    db_user = get_user(user.id)
    if not db_user:
        create_user(user.id, user.username, user.first_name)
        db_user = get_user(user.id)
    
    # Check if phone number exists
    if db_user and not db_user['phone_number']:
        contact_keyboard = [
            [KeyboardButton("📱 Share Phone Number", request_contact=True)],
            [KeyboardButton("❌ Skip")]
        ]
        reply_markup = ReplyKeyboardMarkup(
            contact_keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await update.message.reply_text(
            "📱 Please share your phone number for verification:",
            reply_markup=reply_markup
        )
        return
    
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
    pending = get_pending_transactions_count()
    
    await update.message.reply_text(
        f"🎰 Welcome to MK BINGO, {user.first_name}!\n"
        f"💰 Balance: {balance} ETB\n"
        f"📊 Pending: {pending} transactions",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shared contact information"""
    contact = update.message.contact
    user = update.effective_user
    
    if contact and contact.user_id == user.id:
        update_user_phone(user.id, contact.phone_number)
        await update.message.reply_text("✅ Phone number saved!")
        
        db_user = get_user(user.id)
        is_admin = db_user and db_user['is_admin']
        
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
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    db_user = get_user(user.id)
    
    if data == "balance":
        if db_user:
            await query.edit_message_text(
                f"💳 *Your Balance*\n\n"
                f"Available: *{db_user['balance']} ETB*\n"
                f"Total Deposits: *{db_user['total_deposits']} ETB*",
                parse_mode='Markdown'
            )
    
    elif data == "stats":
        if db_user:
            await query.edit_message_text(
                f"📊 *Your Stats*\n\n"
                f"Games Played: *{db_user['games_played']}*\n"
                f"Total Wins: *{db_user['wins']} ETB*",
                parse_mode='Markdown'
            )
    
    elif data == "deposit":
        await query.edit_message_text(
            "💰 *Deposit Instructions*\n\n"
            "1️⃣ Send money via Telebirr to:\n"
            "   📱 *+251 91 234 5678*\n"
            "   👤 *MK BINGO*\n\n"
            "2️⃣ Reply with the amount you sent\n"
            "3️⃣ Then send the transaction ID\n\n"
            "⚠️ Minimum deposit: *50 ETB*",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_amount'] = True
    
    elif data.startswith("approve_"):
        if user.id != ADMIN_ID:
            await query.edit_message_text("❌ Unauthorized")
            return
        
        tx_id = data.replace("approve_", "")
        telegram_id, amount = approve_transaction(tx_id, ADMIN_ID)
        
        if telegram_id:
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
        else:
            await query.edit_message_text("❌ Transaction not found")
    
    elif data.startswith("reject_"):
        if user.id != ADMIN_ID:
            await query.edit_message_text("❌ Unauthorized")
            return
        
        tx_id = data.replace("reject_", "")
        await query.edit_message_text(f"❌ Deposit Rejected")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (amount and transaction ID)"""
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
        
        db_user = get_user(user.id)
        if not db_user:
            await update.message.reply_text("❌ User not found. Please use /start")
            return
        
        add_transaction(db_user['id'], amount, tx_id)
        
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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"❌ Update {update} caused error {context.error}")

# ==================== MAIN BOT FUNCTION ====================
def run_bot():
    """Run the bot with proper error handling"""
    logger.info("=" * 50)
    logger.info("🤖 Starting Telegram Bot...")
    logger.info("=" * 50)
    
    retry_count = 0
    max_retries = 10
    
    while retry_count < max_retries:
        try:
            # Create application
            application = Application.builder().token(BOT_TOKEN).build()
            
            # Add handlers
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CallbackQueryHandler(button_handler))
            application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
            application.add_error_handler(error_handler)
            
            logger.info("✅ Bot handlers registered successfully")
            logger.info("🔄 Starting polling...")
            
            # Start polling (this blocks)
            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=['message', 'callback_query', 'contact']
            )
            
            # If we get here, polling stopped
            logger.info("⏹️ Bot polling stopped")
            break
            
        except Conflict as e:
            logger.error(f"⚠️ Conflict error: {e}")
            retry_count += 1
            if retry_count < max_retries:
                wait = 10
                logger.info(f"⏱️ Waiting {wait} seconds before retry...")
                time.sleep(wait)
            
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            logger.exception("Full traceback:")
            retry_count += 1
            if retry_count < max_retries:
                wait = 15
                logger.info(f"⏱️ Waiting {wait} seconds before retry...")
                time.sleep(wait)
    
    if retry_count >= max_retries:
        logger.error("❌ Max retries reached. Bot failed to start.")
        sys.exit(1)

# ==================== MAIN ENTRY POINT ====================
if __name__ == '__main__':
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)