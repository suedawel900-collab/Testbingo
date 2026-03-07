# telegram_bot.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import json
import os
from datetime import datetime, timedelta
import random
import string

# Configuration
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_ID = 123456789  # Your Telegram admin ID

# Database files (in production, use real database)
USERS_DB = 'users.json'
PENDING_DB = 'pending.json'
TRANSACTIONS_DB = 'transactions.json'

# Initialize databases
def init_db():
    for db in [USERS_DB, PENDING_DB, TRANSACTIONS_DB]:
        if not os.path.exists(db):
            with open(db, 'w') as f:
                json.dump({}, f)

init_db()

# Load/Save helpers
def load_json(file):
    with open(file, 'r') as f:
        return json.load(f)

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

# User management
class UserManager:
    @staticmethod
    def get_user(user_id):
        users = load_json(USERS_DB)
        return users.get(str(user_id))
    
    @staticmethod
    def create_user(user_id, username, first_name):
        users = load_json(USERS_DB)
        if str(user_id) not in users:
            # New user gets welcome bonus
            bonus_amount = 50  # 50 birr welcome bonus
            users[str(user_id)] = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'balance': bonus_amount,
                'total_deposits': 0,
                'total_bonus': bonus_amount,
                'games_played': 0,
                'wins': 0,
                'joined_date': datetime.now().isoformat(),
                'last_active': datetime.now().isoformat(),
                'referral_code': UserManager.generate_referral_code(),
                'referred_by': None,
                'referrals': []
            }
            save_json(USERS_DB, users)
            return True, bonus_amount
        return False, 0
    
    @staticmethod
    def generate_referral_code():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    @staticmethod
    def update_balance(user_id, amount, transaction_type):
        users = load_json(USERS_DB)
        if str(user_id) in users:
            users[str(user_id)]['balance'] += amount
            users[str(user_id)]['last_active'] = datetime.now().isoformat()
            
            if transaction_type == 'deposit':
                users[str(user_id)]['total_deposits'] += amount
            elif transaction_type == 'bonus':
                users[str(user_id)]['total_bonus'] += amount
            
            save_json(USERS_DB, users)
            
            # Record transaction
            TransactionManager.record_transaction(user_id, amount, transaction_type)
            
            return users[str(user_id)]['balance']
        return None
    
    @staticmethod
    def add_referral(user_id, referred_user_id):
        users = load_json(USERS_DB)
        if str(user_id) in users:
            if 'referrals' not in users[str(user_id)]:
                users[str(user_id)]['referrals'] = []
            users[str(user_id)]['referrals'].append({
                'user_id': referred_user_id,
                'date': datetime.now().isoformat(),
                'bonus_given': 20  # 20 birr referral bonus
            })
            save_json(USERS_DB, users)
            
            # Give referral bonus
            UserManager.update_balance(user_id, 20, 'bonus')
            return True
        return False

# Transaction management
class TransactionManager:
    @staticmethod
    def record_transaction(user_id, amount, transaction_type, tx_id=None, status='completed'):
        transactions = load_json(TRANSACTIONS_DB)
        tx_id = tx_id or f"TX{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"
        
        transactions[tx_id] = {
            'user_id': user_id,
            'amount': amount,
            'type': transaction_type,
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'tx_id': tx_id
        }
        save_json(TRANSACTIONS_DB, transactions)
        return tx_id
    
    @staticmethod
    def get_user_transactions(user_id):
        transactions = load_json(TRANSACTIONS_DB)
        return [t for t in transactions.values() if t['user_id'] == user_id]

# Pending deposits
class PendingManager:
    @staticmethod
    def add_pending(tx_id, user_id, amount):
        pending = load_json(PENDING_DB)
        pending[tx_id] = {
            'user_id': user_id,
            'amount': amount,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }
        save_json(PENDING_DB, pending)
    
    @staticmethod
    def get_pending(tx_id):
        pending = load_json(PENDING_DB)
        return pending.get(tx_id)
    
    @staticmethod
    def update_status(tx_id, status):
        pending = load_json(PENDING_DB)
        if tx_id in pending:
            pending[tx_id]['status'] = status
            pending[tx_id]['processed_at'] = datetime.now().isoformat()
            save_json(PENDING_DB, pending)
            return pending[tx_id]
        return None

# Bot Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    args = context.args
    
    # Check if user exists, create new user with bonus
    is_new, bonus = UserManager.create_user(user.id, user.username, user.first_name)
    
    # Check for referral
    if args and args[0]:
        referrer_id = args[0]
        if str(referrer_id) != str(user.id):
            UserManager.add_referral(referrer_id, user.id)
            # Update referred_by for new user
            users = load_json(USERS_DB)
            if str(user.id) in users:
                users[str(user.id)]['referred_by'] = int(referrer_id)
                save_json(USERS_DB, users)
    
    welcome_message = (
        f"👋 እንኳን ደህና መጡ ወደ ቢንጎ ቦት @{user.username}!\n\n"
    )
    
    if is_new:
        welcome_message += f"🎁 እንኳን ደህና መጡ ቦነስ {bonus} ብር አግኝተዋል!\n\n"
    
    # Get user balance
    user_data = UserManager.get_user(user.id)
    balance = user_data['balance'] if user_data else 0
    
    welcome_message += (
        f"💰 ያለዎት ብር: {balance} ብር\n\n"
        f"Available commands:\n"
        f"/balance - ያለዎትን ብር ይመልከቱ\n"
        f"/deposit - ብር ይሙሉ\n"
        f"/withdraw - ብር ያውጡ\n"
        f"/history - የግብይት ታሪክ\n"
        f"/referral - የማመላከቻ ኮድ ይመልከቱ\n"
        f"/play - ወደ ቢንጎ ጨዋታ ይሂዱ"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎮 ወደ ጨዋታ ይሂዱ", url="https://your-bingo-app.com")],
        [InlineKeyboardButton("💰 ብር ሙላ", callback_data="deposit")]
    ]
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_data = UserManager.get_user(user.id)
    
    if user_data:
        balance = user_data['balance']
        total_deposits = user_data['total_deposits']
        total_bonus = user_data['total_bonus']
        
        message = (
            f"💰 የሂሳብ መረጃ\n\n"
            f"አሁን ያለዎት ብር: {balance} ብር\n"
            f"ጠቅላላ ያስገቡት: {total_deposits} ብር\n"
            f"ጠቅላላ ቦነስ: {total_bonus} ብር\n"
            f"የተጫወቱት ጨዋታ: {user_data['games_played']}\n"
            f"ያሸነፉባቸው ጨዋታዎች: {user_data['wins']}"
        )
    else:
        message = "እባክዎ /start ይጫኑ መጀመሪያ"
    
    await update.message.reply_text(message)

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💳 ቴሌ ብር", callback_data="payment_telebirr")],
        [InlineKeyboardButton("🏦 ባንክ ትራንስፈር", callback_data="payment_bank")],
        [InlineKeyboardButton("↩️ ተመለስ", callback_data="main_menu")]
    ]
    
    await update.message.reply_text(
        "💰 የክፍያ ዘዴ ይምረጡ:\n\n"
        "ማስታወሻ: አነስተኛ ክፍያ 50 ብር ነው",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "payment_telebirr":
        message = (
            "📱 ቴሌ ብር ክፍያ\n\n"
            "1. ወደ ቴሌ ብር 09XXXXXXXX ይላኩ\n"
            "2. የተላከለትን የግብይት መለያ ቁጥር (Transaction ID) ይላኩ\n\n"
            "ለምሳሌ: DC39E2J9ZP\n\n"
            "ከዚህ በታች ይላኩ።"
        )
    elif query.data == "payment_bank":
        message = (
            "🏦 ባንክ ክፍያ\n\n"
            "ወደ ሚከተለው አካውንት ይላኩ፦\n\n"
            "ባንክ: ኮመርሻል ባንክ ኦፍ ኢትዮጵያ\n"
            "አካውንት ስም: Bingo Game PLC\n"
            "አካውንት ቁጥር: 1000001234567\n\n"
            "ከተላከ በኋላ የማረጋገጫ ስላይድ ወይም የግብይት መለያ ይላኩ።"
        )
    elif query.data == "main_menu":
        await start(update, context)
        return
    
    await query.edit_message_text(message)

async def handle_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transaction ID or receipt"""
    tx = update.message.text.strip()
    user = update.message.from_user
    
    # Check if it's a valid transaction ID format
    if len(tx) < 5:
        await update.message.reply_text("❌ የማይሰራ የግብይት መለያ ነው። እባክዎ በትክክል ይሙሉ።")
        return
    
    # Create receipt link (for Telebirr)
    receipt = f"https://transactioninfo.ethiotelecom.et/receipt/{tx}"
    
    # Store pending transaction
    PendingManager.add_pending(tx, user.id, 0)  # Amount will be verified by admin
    
    # Create admin approval buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ አረጋግጥ", callback_data=f"approve_{tx}"),
            InlineKeyboardButton("❌ አትስማማ", callback_data=f"reject_{tx}")
        ],
        [InlineKeyboardButton("💰 መጠን ቀይር", callback_data=f"edit_{tx}")]
    ]
    
    # Send to admin
    admin_message = (
        f"💰 አዲስ የክፍያ ጥያቄ\n\n"
        f"User: @{user.username}\n"
        f"User ID: {user.id}\n"
        f"TX ID: {tx}\n\n"
        f"Receipt Link:\n{receipt}"
    )
    
    await context.bot.send_message(
        ADMIN_ID,
        admin_message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # Confirm to user
    await update.message.reply_text(
        "✅ የክፍያ ጥያቄዎ ደርሷል። በቅርቡ ይረጋገጣል።"
    )

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval/rejection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, tx = data.split("_", 1)
    
    pending_info = PendingManager.get_pending(tx)
    
    if not pending_info:
        await query.edit_message_text("❌ Transaction not found")
        return
    
    user_id = pending_info['user_id']
    
    if action == "approve":
        # Ask for amount
        context.user_data['pending_tx'] = tx
        context.user_data['user_id'] = user_id
        
        await query.edit_message_text(
            f"💰 ለትራንዛክሽን {tx}\n\n"
            f"ምን ያህል ብር ማስገባት ይፈልጋሉ?\n"
            f"ለምሳሌ: 100"
        )
        
    elif action == "reject":
        # Update pending status
        PendingManager.update_status(tx, 'rejected')
        
        # Notify user
        await context.bot.send_message(
            user_id,
            "❌ የክፍያ ጥያቄዎ ውድቅ ሆኗል። እባክዎ እንደገና ይሞክሩ።"
        )
        
        await query.edit_message_text("❌ ክፍያ ውድቅ ሆኗል")
    
    elif action == "edit":
        await query.edit_message_text(
            f"Edit feature coming soon for {tx}"
        )

async def handle_admin_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin entering amount for approval"""
    if update.message.from_user.id != ADMIN_ID:
        return
    
    if 'pending_tx' not in context.user_data:
        return
    
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
        
        tx = context.user_data['pending_tx']
        user_id = context.user_data['user_id']
        
        # Update user balance
        new_balance = UserManager.update_balance(user_id, amount, 'deposit')
        
        # Update pending status
        PendingManager.update_status(tx, 'approved')
        
        # Record transaction
        TransactionManager.record_transaction(user_id, amount, 'deposit', tx)
        
        # Notify user
        await context.bot.send_message(
            user_id,
            f"✅ {amount} ብር በሂሳብዎ ተጨምሯል!\n"
            f"አሁን ያለዎት ብር: {new_balance} ብር\n\n"
            f"ወደ ጨዋታ በመሄድ መጫወት ይችላሉ።"
        )
        
        await context.bot.send_message(
            ADMIN_ID,
            f"✅ {amount} ብር ለተጠቃሚ {user_id} ተጨምሯል"
        )
        
        # Clear pending data
        del context.user_data['pending_tx']
        del context.user_data['user_id']
        
    except ValueError:
        await update.message.reply_text("❌ የማይሰራ ቁጥር ነው። እባክዎ ትክክለኛ ቁጥር ይጠቀሙ።")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_data = UserManager.get_user(user.id)
    
    if not user_data:
        await update.message.reply_text("እባክዎ /start ይጫኑ መጀመሪያ")
        return
    
    balance = user_data['balance']
    
    if balance < 100:
        await update.message.reply_text(
            f"❌ ማውጣት አይችሉም። አነስተኛ መጠን 100 ብር ነው።\n"
            f"ያለዎት ብር: {balance} ብር"
        )
        return
    
    await update.message.reply_text(
        f"💰 ማውጣት የሚፈልጉትን መጠን ይምረጡ:\n\n"
        f"ያለዎት ብር: {balance} ብር",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("100 ብር", callback_data="withdraw_100")],
            [InlineKeyboardButton("200 ብር", callback_data="withdraw_200")],
            [InlineKeyboardButton("500 ብር", callback_data="withdraw_500")],
            [InlineKeyboardButton("ሌላ መጠን", callback_data="withdraw_custom")]
        ])
    )

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = UserManager.get_user(user_id)
    
    if not user_data:
        await query.edit_message_text("እባክዎ /start ይጫኑ መጀመሪያ")
        return
    
    balance = user_data['balance']
    
    if query.data == "withdraw_custom":
        await query.edit_message_text(
            "ማውጣት የሚፈልጉትን መጠን ይላኩ።\n"
            f"ከፍተኛ: {balance} ብር"
        )
        context.user_data['awaiting_withdraw'] = True
        return
    
    amount = int(query.data.split("_")[1])
    
    if amount > balance:
        await query.edit_message_text(f"❌ በቂ ብር የለዎትም። ያለዎት: {balance} ብር")
        return
    
    # Process withdrawal request
    keyboard = [
        [
            InlineKeyboardButton("✅ አረጋግጥ", callback_data=f"wapprove_{user_id}_{amount}"),
            InlineKeyboardButton("❌ አትስማማ", callback_data=f"wreject_{user_id}_{amount}")
        ]
    ]
    
    await context.bot.send_message(
        ADMIN_ID,
        f"💳 የማውጣት ጥያቄ\n\n"
        f"User: @{query.from_user.username}\n"
        f"User ID: {user_id}\n"
        f"Amount: {amount} ብር\n"
        f"Balance: {balance} ብር",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    await query.edit_message_text(
        f"✅ የማውጣት ጥያቄዎ ተልኳል። መጠን: {amount} ብር\n"
        f"በቅርቡ ይረጋገጣል።"
    )

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_withdraw'):
        try:
            amount = int(update.message.text.strip())
            user_id = update.message.from_user.id
            user_data = UserManager.get_user(user_id)
            
            if amount < 50:
                await update.message.reply_text("❌ አነስተኛ መጠን 50 ብር ነው።")
                return
            
            if amount > user_data['balance']:
                await update.message.reply_text(f"❌ በቂ ብር የለዎትም። ያለዎት: {user_data['balance']} ብር")
                return
            
            # Process withdrawal
            keyboard = [
                [
                    InlineKeyboardButton("✅ አረጋግጥ", callback_data=f"wapprove_{user_id}_{amount}"),
                    InlineKeyboardButton("❌ አትስማማ", callback_data=f"wreject_{user_id}_{amount}")
                ]
            ]
            
            await context.bot.send_message(
                ADMIN_ID,
                f"💳 የማውጣት ጥያቄ\n\n"
                f"User: @{update.message.from_user.username}\n"
                f"User ID: {user_id}\n"
                f"Amount: {amount} ብር\n"
                f"Balance: {user_data['balance']} ብር",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            await update.message.reply_text(
                f"✅ የማውጣት ጥያቄዎ ተልኳል። መጠን: {amount} ብር"
            )
            
            del context.user_data['awaiting_withdraw']
            
        except ValueError:
            await update.message.reply_text("❌ የማይሰራ ቁጥር ነው። እባክዎ ትክክለኛ ቁጥር ይጠቀሙ።")

async def handle_withdraw_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, user_id, amount = data.split("_")
    user_id = int(user_id)
    amount = int(amount)
    
    if data.startswith("wapprove"):
        # Update balance
        new_balance = UserManager.update_balance(user_id, -amount, 'withdrawal')
        
        # Record transaction
        TransactionManager.record_transaction(user_id, amount, 'withdrawal')
        
        # Notify user
        await context.bot.send_message(
            user_id,
            f"✅ {amount} ብር ማውጣት ተረጋግጧል!\n"
            f"አዲስ ቀሪ ሂሳብ: {new_balance} ብር"
        )
        
        await query.edit_message_text(f"✅ {amount} ብር ማውጣት ተረጋግጧል")
        
    elif data.startswith("wreject"):
        await context.bot.send_message(
            user_id,
            f"❌ {amount} ብር ማውጣት ውድቅ ሆኗል። እባክዎ እንደገና ይሞክሩ።"
        )
        
        await query.edit_message_text(f"❌ {amount} ብር ማውጣት ውድቅ ሆኗል")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    transactions = TransactionManager.get_user_transactions(user_id)
    
    if not transactions:
        await update.message.reply_text("ምንም የግብይት ታሪክ የለም")
        return
    
    # Sort by timestamp (newest first)
    transactions.sort(key=lambda x: x['timestamp'], reverse=True)
    
    message = "📋 የግብይት ታሪክ (የመጨረሻ 10)\n\n"
    
    for tx in transactions[:10]:
        date = datetime.fromisoformat(tx['timestamp']).strftime("%Y-%m-%d %H:%M")
        emoji = "✅" if tx['type'] == 'deposit' else "💳" if tx['type'] == 'withdrawal' else "🎁"
        message += f"{emoji} {tx['type']}: {tx['amount']} ብር\n"
        message += f"   🕐 {date}\n"
        message += f"   🆔 {tx['tx_id'][:8]}...\n\n"
    
    await update.message.reply_text(message)

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data = UserManager.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("እባክዎ /start ይጫኑ መጀመሪያ")
        return
    
    referral_code = user_data['referral_code']
    referrals = user_data.get('referrals', [])
    referral_link = f"https://t.me/YourBotUsername?start={referral_code}"
    
    message = (
        f"🔗 የማመላከቻ ኮድዎ\n\n"
        f"ኮድ: {referral_code}\n"
        f"ሊንክ: {referral_link}\n\n"
        f"ያመለከቷቸው: {len(referrals)} ሰዎች\n"
        f"ከማመላከቻ ያገኙት ቦነስ: {len(referrals) * 20} ብር\n\n"
        f"አዲስ ተጠቃሚ ሲመጣ 20 ብር ቦነስ ያገኛሉ!"
    )
    
    share_button = [[InlineKeyboardButton("📤 አጋራ", url=f"https://t.me/share/url?url={referral_link}&text=Join Bingo Game!")]]
    
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(share_button)
    )

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_data = UserManager.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("እባክዎ /start ይጫኑ መጀመሪያ")
        return
    
    # Generate auth token for web app
    auth_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # Store token temporarily
    context.user_data['auth_token'] = {
        'token': auth_token,
        'user_id': user_id,
        'expires': (datetime.now() + timedelta(minutes=5)).isoformat()
    }
    
    webapp_url = f"https://your-bingo-app.com?user={user_id}&token={auth_token}"
    
    keyboard = [
        [InlineKeyboardButton("🎮 ወደ ጨዋታ ይሂዱ", url=webapp_url)],
        [InlineKeyboardButton("💰 ብር ሙላ", callback_data="deposit")]
    ]
    
    await update.message.reply_text(
        f"🎮 ወደ ቢንጎ ጨዋታ እንኳን ደህና መጡ!\n\n"
        f"ያለዎት ብር: {user_data['balance']} ብር",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "deposit":
        await deposit(update, context)
    elif query.data.startswith("payment_"):
        await handle_payment_method(update, context)
    elif query.data.startswith("withdraw_"):
        await handle_withdraw(update, context)

# Main app setup
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("play", play))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transaction))
    app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, handle_admin_amount))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$'), handle_withdraw_amount))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(handle_admin_actions, pattern="^(approve|reject|edit)_"))
    app.add_handler(CallbackQueryHandler(handle_withdraw_approval, pattern="^(wapprove|wreject)_"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🤖 Bingo Payment Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()