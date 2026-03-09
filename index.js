// index.js - Main Telegram Bot File
require('dotenv').config();
const TelegramBot = require('node-telegram-bot-api');
const sqlite3 = require('sqlite3').verbose();
const { open } = require('sqlite');
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const winston = require('winston');
const path = require('path');

// ==================== CONFIGURATION ====================
const token = process.env.BOT_TOKEN;
const adminIds = process.env.ADMIN_IDS ? process.env.ADMIN_IDS.split(',').map(id => parseInt(id)) : [];
const PORT = process.env.PORT || 3000;
const DB_PATH = process.env.DB_PATH || './bingo.db';

// Validate bot token
if (!token || token === 'YOUR_BOT_TOKEN_HERE') {
    console.error('❌ Please set your BOT_TOKEN in .env file!');
    process.exit(1);
}

// Initialize bot
const bot = new TelegramBot(token, { 
    polling: true,
    polling: {
        interval: 300,
        autoStart: true,
        params: {
            timeout: 10
        }
    }
});

// ==================== LOGGER SETUP ====================
const logger = winston.createLogger({
    level: 'info',
    format: winston.format.combine(
        winston.format.timestamp(),
        winston.format.json()
    ),
    transports: [
        new winston.transports.File({ filename: 'error.log', level: 'error' }),
        new winston.transports.File({ filename: 'combined.log' }),
        new winston.transports.Console({
            format: winston.format.simple()
        })
    ]
});

// ==================== DATABASE SETUP ====================
let db;

async function initializeDatabase() {
    try {
        db = await open({
            filename: DB_PATH,
            driver: sqlite3.Database
        });

        await db.exec(`
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance INTEGER DEFAULT ${process.env.DEFAULT_BALANCE || 1000},
                total_wins INTEGER DEFAULT 0,
                total_cards_bought INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                total_won INTEGER DEFAULT 0,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS games (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_type TEXT DEFAULT 'full house',
                prize_amount INTEGER DEFAULT ${process.env.DEFAULT_PRIZE || 2000},
                card_price INTEGER DEFAULT ${process.env.DEFAULT_CARD_PRICE || 10},
                status TEXT DEFAULT 'waiting',
                called_numbers TEXT DEFAULT '[]',
                winners TEXT DEFAULT '[]',
                total_players INTEGER DEFAULT 0,
                total_cards INTEGER DEFAULT 0,
                started_by INTEGER,
                started_at DATETIME,
                ended_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cards (
                card_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_id INTEGER,
                card_number INTEGER UNIQUE,
                numbers TEXT,
                is_winner BOOLEAN DEFAULT 0,
                marked_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (game_id) REFERENCES games(game_id)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT CHECK(type IN ('purchase', 'win', 'bonus', 'refund')),
                game_id INTEGER,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (game_id) REFERENCES games(game_id)
            );

            CREATE TABLE IF NOT EXISTS called_numbers_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER,
                number INTEGER,
                called_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(game_id)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_user_game ON cards(user_id, game_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_games_status ON games(status);
        `);

        logger.info('✅ Database initialized successfully');
    } catch (error) {
        logger.error('❌ Database initialization failed:', error);
        process.exit(1);
    }
}

// ==================== EXPRESS SERVER SETUP ====================
const app = express();
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(morgan('combined'));
app.use(express.static(path.join(__dirname, 'public')));

// ==================== BOT ERROR HANDLING ====================
bot.on('polling_error', (error) => {
    logger.error('Polling error:', error);
});

bot.on('error', (error) => {
    logger.error('Bot error:', error);
});

// ==================== HELPER FUNCTIONS ====================

async function registerUser(msg) {
    const userId = msg.from.id;
    const username = msg.from.username || `user_${userId}`;
    const firstName = msg.from.first_name || '';
    const lastName = msg.from.last_name || '';

    try {
        const existing = await db.get('SELECT * FROM users WHERE user_id = ?', userId);
        
        if (!existing) {
            await db.run(
                'INSERT INTO users (user_id, username, first_name, last_name, balance, created_at, last_active) VALUES (?, ?, ?, ?, ?, ?, ?)',
                [userId, username, firstName, lastName, parseInt(process.env.DEFAULT_BALANCE || 1000), new Date().toISOString(), new Date().toISOString()]
            );
            logger.info(`New user registered: ${username} (${userId})`);
            return true;
        } else {
            // Update last active
            await db.run(
                'UPDATE users SET last_active = ?, username = ?, first_name = ?, last_name = ? WHERE user_id = ?',
                [new Date().toISOString(), username, firstName, lastName, userId]
            );
            return false;
        }
    } catch (error) {
        logger.error('Error registering user:', error);
        return false;
    }
}

async function generateCardNumber() {
    let number;
    let exists;
    const maxAttempts = 100;
    let attempts = 0;
    
    do {
        number = Math.floor(Math.random() * 900) + 100; // 100-999
        exists = await db.get('SELECT card_id FROM cards WHERE card_number = ?', number);
        attempts++;
        if (attempts > maxAttempts) {
            // If we can't find a unique number, use timestamp
            number = parseInt(Date.now().toString().slice(-6));
            break;
        }
    } while (exists);
    
    return number;
}

function generateBingoCard(cardNumber) {
    let nums = [];
    let seed = cardNumber || Math.floor(Math.random() * 1000);
    
    for (let col = 0; col < 5; col++) {
        let min = col * 15 + 1;
        let max = (col + 1) * 15;
        
        let colNumbers = [];
        while (colNumbers.length < 5) {
            let n = ((seed * (col + 1) + colNumbers.length * 7) % (max - min + 1)) + min;
            if (!colNumbers.includes(n)) {
                colNumbers.push(n);
            }
        }
        // Sort column numbers
        colNumbers.sort((a, b) => a - b);
        nums.push(...colNumbers);
    }
    
    nums[12] = "FREE";
    return nums;
}

function formatCard(numbers, calledNumbers = []) {
    let result = '```\n';
    result += '╔═══════════════════════╗\n';
    result += '║   B   I   N   G   O   ║\n';
    result += '╠═══════════════════════╣\n';
    
    // Card grid
    for (let row = 0; row < 5; row++) {
        result += '║';
        for (let col = 0; col < 5; col++) {
            let index = row * 5 + col;
            let num = numbers[index];
            
            if (num === 'FREE') {
                result += '  ★  ';
            } else if (calledNumbers.includes(num)) {
                result += `  ✓  `;
            } else {
                result += ` ${num.toString().padStart(2, ' ')}  `;
            }
        }
        result += '║\n';
    }
    
    result += '╚═══════════════════════╝\n';
    result += '```';
    return result;
}

function formatCardPreview(numbers) {
    let result = '```\n';
    result += '┌───────────────┐\n';
    result += '│ B  I  N  G  O │\n';
    result += '├───────────────┤\n';
    
    for (let row = 0; row < 5; row++) {
        result += '│';
        for (let col = 0; col < 5; col++) {
            let index = row * 5 + col;
            let num = numbers[index];
            if (num === 'FREE') {
                result += ' ★ ';
            } else {
                result += ` ${num.toString().padStart(2, ' ')} `;
            }
        }
        result += '│\n';
    }
    
    result += '└───────────────┘\n';
    result += '```';
    return result;
}

function checkCardForWin(card, calledNumbers, gameType) {
    // Helper function to check if a line (row/col) is complete
    const isLineComplete = (indices) => {
        return indices.every(index => 
            card[index] === "FREE" || calledNumbers.includes(card[index])
        );
    };

    switch(gameType) {
        case 'full house':
            const allMarked = card.every((num, index) => 
                num === "FREE" || calledNumbers.includes(num)
            );
            if (allMarked) return { type: 'full house', cells: card.map((_, i) => i) };
            break;
            
        case '1 row':
            for (let row = 0; row < 5; row++) {
                let indices = [0,1,2,3,4].map(col => row * 5 + col);
                if (isLineComplete(indices)) {
                    return { type: 'row', cells: indices };
                }
            }
            break;
            
        case '1 column':
            for (let col = 0; col < 5; col++) {
                let indices = [0,1,2,3,4].map(row => row * 5 + col);
                if (isLineComplete(indices)) {
                    return { type: 'column', cells: indices };
                }
            }
            break;
            
        case '4 corners':
            let corners = [0, 4, 20, 24];
            if (isLineComplete(corners)) {
                return { type: 'corners', cells: corners };
            }
            break;
            
        case 'X shape':
            let xIndices = [0, 4, 6, 8, 12, 16, 18, 20, 24];
            if (isLineComplete(xIndices)) {
                return { type: 'X shape', cells: xIndices };
            }
            break;
            
        case 'random':
            return checkCardForWin(card, calledNumbers, 'full house') || 
                   checkCardForWin(card, calledNumbers, '1 row') || 
                   checkCardForWin(card, calledNumbers, '1 column') ||
                   checkCardForWin(card, calledNumbers, '4 corners') ||
                   checkCardForWin(card, calledNumbers, 'X shape');
    }
    return null;
}

async function checkWinners(gameId, lastNumber) {
    try {
        const game = await db.get('SELECT * FROM games WHERE game_id = ?', gameId);
        if (!game) return;

        const cards = await db.all('SELECT * FROM cards WHERE game_id = ? AND is_winner = 0', gameId);
        const calledNumbers = JSON.parse(game.called_numbers);
        let winners = JSON.parse(game.winners);
        let newWinners = [];

        for (const card of cards) {
            const numbers = JSON.parse(card.numbers);
            const win = checkCardForWin(numbers, calledNumbers, game.game_type);
            
            if (win) {
                // Mark as winner
                await db.run('UPDATE cards SET is_winner = 1 WHERE card_id = ?', card.card_id);
                
                // Add to winners list
                newWinners.push({
                    card_number: card.card_number,
                    win_type: win.type,
                    winning_cells: win.cells,
                    called_number: lastNumber,
                    user_id: card.user_id
                });

                winners.push({
                    card_number: card.card_number,
                    win_type: win.type,
                    winning_cells: win.cells,
                    called_number: lastNumber
                });

                // Award prize to user
                const prizePerWinner = game.prize_amount / (winners.length);
                
                // Update user balance and stats
                await db.run(
                    `UPDATE users SET 
                        balance = balance + ?, 
                        total_wins = total_wins + 1,
                        total_won = total_won + ?
                    WHERE user_id = ?`,
                    [prizePerWinner, prizePerWinner, card.user_id]
                );

                // Record win transaction
                await db.run(
                    `INSERT INTO transactions 
                        (user_id, amount, type, game_id, description) 
                    VALUES (?, ?, ?, ?, ?)`,
                    [card.user_id, prizePerWinner, 'win', gameId, `Won with ${win.type}`]
                );

                // Notify the winner
                try {
                    await bot.sendMessage(card.user_id, 
                        `🎉🎉 *CONGRATULATIONS! YOU WON!* 🎉🎉\n\n` +
                        `🏆 Card #${card.card_number}\n` +
                        `🎯 Win Type: *${win.type}*\n` +
                        `💰 Prize: *${prizePerWinner.toFixed(0)} ETB*\n` +
                        `🎲 Winning Number: ${lastNumber}\n\n` +
                        `Check your balance with /balance`,
                        { parse_mode: 'Markdown' }
                    );
                } catch (error) {
                    logger.error('Error notifying winner:', error);
                }
            }
        }

        // Update game with winners
        if (newWinners.length > 0) {
            await db.run('UPDATE games SET winners = ? WHERE game_id = ?', 
                [JSON.stringify(winners), gameId]
            );
            
            // Announce winners to all players
            await announceWinners(gameId, newWinners);
        }

        return newWinners;
    } catch (error) {
        logger.error('Error checking winners:', error);
        return [];
    }
}

async function announceWinners(gameId, newWinners) {
    try {
        const game = await db.get('SELECT * FROM games WHERE game_id = ?', gameId);
        const prizePerWinner = game.prize_amount / JSON.parse(game.winners).length;

        let message = `🏆 *NEW WINNER(S) ANNOUNCEMENT!* 🏆\n\n`;
        
        for (let i = 0; i < newWinners.length; i++) {
            const winner = newWinners[i];
            const user = await db.get(
                'SELECT username FROM users WHERE user_id = ?',
                winner.user_id
            );
            
            message += `*Winner #${i + 1}*\n`;
            message += `👤 Player: @${user?.username || 'Unknown'}\n`;
            message += `🎫 Card: #${winner.card_number}\n`;
            message += `🏆 Type: *${winner.win_type}*\n`;
            message += `💰 Prize: *${prizePerWinner.toFixed(0)} ETB*\n`;
            message += `─────────────\n`;
        }

        message += `\n🎯 Game Type: ${game.game_type}\n`;
        message += `📊 Total Called: ${JSON.parse(game.called_numbers).length}/75`;

        await notifyAllPlayers(message);
    } catch (error) {
        logger.error('Error announcing winners:', error);
    }
}

async function notifyAllUsers(message, parseMode = 'Markdown') {
    try {
        const users = await db.all('SELECT user_id FROM users');
        let successCount = 0;
        let failCount = 0;
        
        for (const user of users) {
            try {
                await bot.sendMessage(user.user_id, message, { parse_mode: parseMode });
                successCount++;
                // Add small delay to avoid rate limiting
                await new Promise(resolve => setTimeout(resolve, 50));
            } catch (error) {
                failCount++;
                logger.error(`Error notifying user ${user.user_id}:`, error.message);
            }
        }
        
        logger.info(`Notifications sent: ${successCount} success, ${failCount} failed`);
    } catch (error) {
        logger.error('Error in notifyAllUsers:', error);
    }
}

async function notifyAllPlayers(message, parseMode = 'Markdown') {
    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) return;
        
        const players = await db.all(
            'SELECT DISTINCT user_id FROM cards WHERE game_id = ?',
            game.game_id
        );
        
        for (const player of players) {
            try {
                await bot.sendMessage(player.user_id, message, { parse_mode: parseMode });
                await new Promise(resolve => setTimeout(resolve, 50));
            } catch (error) {
                logger.error(`Error notifying player ${player.user_id}:`, error.message);
            }
        }
    } catch (error) {
        logger.error('Error in notifyAllPlayers:', error);
    }
}

async function updateGameStats(gameId) {
    try {
        const totalCards = await db.get('SELECT COUNT(*) as count FROM cards WHERE game_id = ?', gameId);
        const totalPlayers = await db.get('SELECT COUNT(DISTINCT user_id) as count FROM cards WHERE game_id = ?', gameId);
        
        await db.run(
            'UPDATE games SET total_players = ?, total_cards = ? WHERE game_id = ?',
            [totalPlayers.count, totalCards.count, gameId]
        );
        
        logger.info(`Game #${gameId} Stats - Players: ${totalPlayers.count}, Cards: ${totalCards.count}`);
    } catch (error) {
        logger.error('Error updating game stats:', error);
    }
}

function isAdmin(userId) {
    return adminIds.includes(userId);
}

// ==================== BOT COMMANDS ====================

// Start command
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
        const isNewUser = await registerUser(msg);
        
        const welcomeMessage = `
🎰 *WELCOME TO MK BINGO DELUXE!* 🎰

Hey ${msg.from.first_name}! Ready to play Bingo?

💰 Your current balance: *${process.env.DEFAULT_BALANCE || 1000} ETB*

*Available Commands:*
🎫 /buy [quantity] - Buy Bingo cards (1-10 cards)
🎮 /mycards - View your cards
📋 /game - Current game status
🏆 /winners - View winners
💳 /balance - Check your balance
📊 /stats - Your statistics
👥 /players - Active players

${isAdmin(msg.from.id) ? '*Admin Commands:*\n🎲 /call - Call next number\n🔄 /newgame - Start new round\n⚙️ /settype [type] - Set game type\n💰 /setprize [amount] - Set prize\n💵 /setprice [amount] - Set card price\n⏹️ /endgame - End current game\n' : ''}
Join now and win big! 🏆
        `;

        await bot.sendMessage(chatId, welcomeMessage, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /start:', error);
        await bot.sendMessage(chatId, '❌ An error occurred. Please try again.');
    }
});

// Buy cards command
bot.onText(/\/buy(\s+(\d+))?/, async (msg, match) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    
    try {
        let quantity = match && match[2] ? parseInt(match[2]) : 1;
        const maxCards = parseInt(process.env.MAX_CARDS_PER_BUY || 10);
        
        // Validate quantity
        if (quantity < 1 || quantity > maxCards) {
            return bot.sendMessage(chatId, `❌ Please buy between 1 and ${maxCards} cards.`);
        }

        // Get user balance
        const user = await db.get('SELECT balance FROM users WHERE user_id = ?', userId);
        
        if (!user) {
            return bot.sendMessage(chatId, '❌ Please use /start first to register.');
        }
        
        // Get current game
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Please wait for admin to start a new round.');
        }

        const totalCost = quantity * game.card_price;

        if (user.balance < totalCost) {
            return bot.sendMessage(chatId, 
                `❌ Insufficient balance!\nYour balance: ${user.balance} ETB\nNeed: ${totalCost} ETB`
            );
        }

        // Generate and save cards
        const cards = [];
        for (let i = 0; i < quantity; i++) {
            const cardNumber = await generateCardNumber();
            const cardNumbers = generateBingoCard(cardNumber);
            
            await db.run(
                'INSERT INTO cards (user_id, game_id, card_number, numbers) VALUES (?, ?, ?, ?)',
                [userId, game.game_id, cardNumber, JSON.stringify(cardNumbers)]
            );
            
            cards.push({ number: cardNumber, numbers: cardNumbers });
        }

        // Update user balance and stats
        await db.run(
            `UPDATE users SET 
                balance = balance - ?, 
                total_cards_bought = total_cards_bought + ?,
                total_spent = total_spent + ?
            WHERE user_id = ?`,
            [totalCost, quantity, totalCost, userId]
        );

        // Record transaction
        await db.run(
            'INSERT INTO transactions (user_id, amount, type, game_id, description) VALUES (?, ?, ?, ?, ?)',
            [userId, -totalCost, 'purchase', game.game_id, `Bought ${quantity} cards`]
        );

        // Send success message with cards
        let cardMessage = `✅ *Successfully bought ${quantity} card(s) for ${totalCost} ETB!*\n\n`;
        cardMessage += `💰 New balance: ${user.balance - totalCost} ETB\n\n`;
        cardMessage += `*YOUR CARDS:*\n`;

        for (const card of cards) {
            cardMessage += `\n🎫 *Card #${card.number}*\n`;
            cardMessage += formatCardPreview(card.numbers);
        }

        await bot.sendMessage(chatId, cardMessage, { parse_mode: 'Markdown' });

        // Update game stats
        await updateGameStats(game.game_id);
    } catch (error) {
        logger.error('Error in /buy:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while buying cards. Please try again.');
    }
});

// View my cards
bot.onText(/\/mycards/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    try {
        const game = await db.get('SELECT * FROM games WHERE status IN ("active", "waiting") ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, 'No active game.');
        }

        const cards = await db.all(
            'SELECT * FROM cards WHERE user_id = ? AND game_id = ? ORDER BY card_number',
            [userId, game.game_id]
        );

        if (cards.length === 0) {
            return bot.sendMessage(chatId, 'You have no cards in the current game. Use /buy to purchase cards!');
        }

        const calledNumbers = JSON.parse(game.called_numbers);
        
        let message = `🎮 *Your Cards (Game #${game.game_id})*\n\n`;
        message += `Game Type: ${game.game_type}\n`;
        message += `Prize: ${game.prize_amount} ETB\n`;
        message += `Called Numbers: ${calledNumbers.length}/75\n\n`;

        // Split cards into chunks to avoid message too long error
        const chunks = [];
        let currentChunk = '';
        
        for (const card of cards) {
            const numbers = JSON.parse(card.numbers);
            const markedCount = numbers.filter(n => 
                n !== 'FREE' && calledNumbers.includes(n)
            ).length;
            
            let cardText = `🎫 *Card #${card.card_number}* (${markedCount}/24 marked)\n`;
            
            if (card.is_winner) {
                cardText += `🏆 *WINNER CARD!*\n`;
            }
            
            cardText += formatCard(numbers, calledNumbers);
            cardText += '\n';
            
            if ((currentChunk + cardText).length > 3500) {
                chunks.push(currentChunk);
                currentChunk = cardText;
            } else {
                currentChunk += cardText;
            }
        }
        
        if (currentChunk) {
            chunks.push(currentChunk);
        }

        // Send first chunk with header
        await bot.sendMessage(chatId, message + chunks[0], { parse_mode: 'Markdown' });
        
        // Send remaining chunks
        for (let i = 1; i < chunks.length; i++) {
            await bot.sendMessage(chatId, chunks[i], { parse_mode: 'Markdown' });
        }
    } catch (error) {
        logger.error('Error in /mycards:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching your cards.');
    }
});

// Game status
bot.onText(/\/game/, async (msg) => {
    const chatId = msg.chat.id;

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Please wait for admin to start a new round.');
        }

        const calledNumbers = JSON.parse(game.called_numbers);
        const players = await db.get(
            'SELECT COUNT(DISTINCT user_id) as count FROM cards WHERE game_id = ?',
            game.game_id
        );
        const totalCards = await db.get(
            'SELECT COUNT(*) as count FROM cards WHERE game_id = ?',
            game.game_id
        );

        let message = `🎮 *CURRENT GAME STATUS*\n\n`;
        message += `📊 Game ID: *${game.game_id}*\n`;
        message += `📊 Game Type: *${game.game_type}*\n`;
        message += `💰 Prize: *${game.prize_amount} ETB*\n`;
        message += `💵 Card Price: *${game.card_price} ETB*\n`;
        message += `👥 Players: *${players.count}*\n`;
        message += `🃏 Cards Sold: *${totalCards.count}*\n`;
        message += `📢 Called Numbers: *${calledNumbers.length}/75*\n\n`;

        if (calledNumbers.length > 0) {
            message += '*Recent Numbers:*\n';
            const recent = calledNumbers.slice(-15);
            
            // Group numbers by letter
            const bNumbers = recent.filter(n => n <= 15).map(n => `B-${n}`);
            const iNumbers = recent.filter(n => n > 15 && n <= 30).map(n => `I-${n}`);
            const nNumbers = recent.filter(n => n > 30 && n <= 45).map(n => `N-${n}`);
            const gNumbers = recent.filter(n => n > 45 && n <= 60).map(n => `G-${n}`);
            const oNumbers = recent.filter(n => n > 60).map(n => `O-${n}`);
            
            if (bNumbers.length) message += bNumbers.join(' ') + '\n';
            if (iNumbers.length) message += iNumbers.join(' ') + '\n';
            if (nNumbers.length) message += nNumbers.join(' ') + '\n';
            if (gNumbers.length) message += gNumbers.join(' ') + '\n';
            if (oNumbers.length) message += oNumbers.join(' ') + '\n';
        }

        const winners = JSON.parse(game.winners);
        if (winners.length > 0) {
            message += '\n🏆 *WINNERS:*\n';
            winners.forEach((winner, i) => {
                message += `${i + 1}. Card #${winner.card_number} - ${winner.win_type}\n`;
            });
        }

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /game:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching game status.');
    }
});

// Check balance
bot.onText(/\/balance/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    try {
        const user = await db.get(
            'SELECT balance, total_wins, total_cards_bought, total_spent, total_won FROM users WHERE user_id = ?', 
            userId
        );

        if (!user) {
            return bot.sendMessage(chatId, '❌ Please use /start first to register.');
        }

        const netProfit = (user.total_won || 0) - (user.total_spent || 0);

        await bot.sendMessage(chatId, 
            `💰 *Your Balance*\n\n` +
            `Current Balance: *${user.balance} ETB*\n` +
            `Total Wins: *${user.total_wins || 0}*\n` +
            `Cards Bought: *${user.total_cards_bought || 0}*\n` +
            `Total Spent: *${user.total_spent || 0} ETB*\n` +
            `Total Won: *${user.total_won || 0} ETB*\n` +
            `Net Profit: *${netProfit >= 0 ? '+' : ''}${netProfit} ETB*\n\n` +
            `Use /buy to purchase cards!`,
            { parse_mode: 'Markdown' }
        );
    } catch (error) {
        logger.error('Error in /balance:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching your balance.');
    }
});

// View winners
bot.onText(/\/winners/, async (msg) => {
    const chatId = msg.chat.id;

    try {
        const game = await db.get('SELECT * FROM games WHERE winners != "[]" ORDER BY game_id DESC LIMIT 1');
        
        if (!game || JSON.parse(game.winners).length === 0) {
            return bot.sendMessage(chatId, 'No winners yet in the current game.');
        }

        const winners = JSON.parse(game.winners);
        const prizePerWinner = game.prize_amount / winners.length;
        
        let message = `🏆 *WINNERS - Game #${game.game_id}*\n\n`;

        for (let i = 0; i < winners.length; i++) {
            const winner = winners[i];
            const user = await db.get(
                'SELECT username FROM users JOIN cards ON users.user_id = cards.user_id WHERE cards.card_number = ?',
                winner.card_number
            );
            
            message += `*Winner #${i + 1}*\n`;
            message += `👤 Player: @${user?.username || 'Unknown'}\n`;
            message += `🎫 Card: #${winner.card_number}\n`;
            message += `🏆 Win Type: *${winner.win_type}*\n`;
            message += `💰 Prize: *${prizePerWinner.toFixed(0)} ETB*\n`;
            message += `─────────────\n`;
        }

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /winners:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching winners.');
    }
});

// Player statistics
bot.onText(/\/stats/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    try {
        const stats = await db.get(`
            SELECT 
                u.balance,
                u.total_wins,
                u.total_cards_bought,
                u.total_spent,
                u.total_won,
                COUNT(DISTINCT t.transaction_id) as total_transactions,
                (SELECT COUNT(*) FROM cards WHERE user_id = ? AND is_winner = 1) as winning_cards
            FROM users u
            LEFT JOIN transactions t ON u.user_id = t.user_id
            WHERE u.user_id = ?
            GROUP BY u.user_id
        `, [userId, userId]);

        if (!stats) {
            return bot.sendMessage(chatId, '❌ Please use /start first to register.');
        }

        const winRate = stats.total_cards_bought ? 
            ((stats.winning_cards / stats.total_cards_bought) * 100).toFixed(1) : 0;
        const roi = stats.total_spent ? 
            (((stats.total_won - stats.total_spent) / stats.total_spent) * 100).toFixed(1) : 0;

        let message = `📊 *Your Statistics*\n\n`;
        message += `💰 Current Balance: *${stats.balance} ETB*\n`;
        message += `🏆 Total Wins: *${stats.total_wins || 0}*\n`;
        message += `🎫 Winning Cards: *${stats.winning_cards || 0}*\n`;
        message += `🃏 Cards Bought: *${stats.total_cards_bought || 0}*\n`;
        message += `📈 Win Rate: *${winRate}%*\n`;
        message += `💸 Total Spent: *${stats.total_spent || 0} ETB*\n`;
        message += `💵 Total Won: *${stats.total_won || 0} ETB*\n`;
        message += `📊 ROI: *${roi}%*\n`;
        message += `💳 Transactions: *${stats.total_transactions || 0}*`;

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /stats:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching your statistics.');
    }
});

// Active players
bot.onText(/\/players/, async (msg) => {
    const chatId = msg.chat.id;

    try {
        const game = await db.get('SELECT game_id FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, 'No active game.');
        }

        const players = await db.all(`
            SELECT 
                u.username,
                u.user_id,
                COUNT(c.card_id) as card_count,
                SUM(CASE WHEN c.is_winner = 1 THEN 1 ELSE 0 END) as winner_count
            FROM users u
            JOIN cards c ON u.user_id = c.user_id
            WHERE c.game_id = ?
            GROUP BY u.user_id
            ORDER BY card_count DESC
            LIMIT 20
        `, game.game_id);

        if (players.length === 0) {
            return bot.sendMessage(chatId, 'No players in current game.');
        }

        let message = `👥 *Active Players (${players.length})*\n\n`;
        players.forEach((player, index) => {
            message += `${index + 1}. @${player.username || 'Unknown'}\n`;
            message += `   🃏 ${player.card_count} cards`;
            if (player.winner_count > 0) {
                message += ` 🏆 ${player.winner_count} win(s)`;
            }
            message += '\n';
        });

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /players:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching players.');
    }
});

// ==================== ADMIN COMMANDS ====================

// Start new game (Admin only)
bot.onText(/\/newgame/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    try {
        // End current active game if exists
        await db.run('UPDATE games SET status = "ended", ended_at = ? WHERE status = "active"', 
            [new Date().toISOString()]);

        // Create new game
        const result = await db.run(
            `INSERT INTO games 
                (game_type, prize_amount, card_price, status, started_by, started_at) 
            VALUES (?, ?, ?, ?, ?, ?)`,
            ['full house', 
             parseInt(process.env.DEFAULT_PRIZE || 2000), 
             parseInt(process.env.DEFAULT_CARD_PRICE || 10), 
             'active', 
             userId, 
             new Date().toISOString()]
        );

        await bot.sendMessage(chatId, 
            `✅ *New Bingo Round Started!*\n\n` +
            `Game ID: #${result.lastID}\n` +
            `Type: full house\n` +
            `Prize: ${process.env.DEFAULT_PRIZE || 2000} ETB\n` +
            `Card Price: ${process.env.DEFAULT_CARD_PRICE || 10} ETB\n\n` +
            `Players can now buy cards using /buy [quantity]`,
            { parse_mode: 'Markdown' }
        );

        // Notify all users
        await notifyAllUsers('🎰 *NEW BINGO ROUND STARTED!*\n\nUse /buy to purchase cards and join the game!');
        
        logger.info(`New game started by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /newgame:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while starting new game.');
    }
});

// Call next number (Admin only)
bot.onText(/\/call/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Use /newgame to start one.');
        }

        const calledNumbers = JSON.parse(game.called_numbers);
        
        if (calledNumbers.length >= 75) {
            return bot.sendMessage(chatId, '❌ All numbers have been called!');
        }

        // Generate next number
        let number;
        do {
            number = Math.floor(Math.random() * 75) + 1;
        } while (calledNumbers.includes(number));

        calledNumbers.push(number);
        
        // Update game
        await db.run(
            'UPDATE games SET called_numbers = ? WHERE game_id = ?',
            [JSON.stringify(calledNumbers), game.game_id]
        );

        // Log called number
        await db.run(
            'INSERT INTO called_numbers_log (game_id, number) VALUES (?, ?)',
            [game.game_id, number]
        );

        // Check for winners
        const newWinners = await checkWinners(game.game_id, number);

        // Format number for display
        let letter = '';
        if (number <= 15) letter = 'B';
        else if (number <= 30) letter = 'I';
        else if (number <= 45) letter = 'N';
        else if (number <= 60) letter = 'G';
        else letter = 'O';

        // Announce number to admin
        const numberMessage = `🎲 *NEW NUMBER CALLED!*\n\n` +
            `🔢 Number: *${letter}-${number}*\n` +
            `📊 Total Called: *${calledNumbers.length}/75*\n` +
            `${newWinners.length > 0 ? `🏆 New Winners: *${newWinners.length}*` : ''}`;

        await bot.sendMessage(chatId, numberMessage, { parse_mode: 'Markdown' });
        
        // Also send to all players
        const playerMessage = `🎲 *NEW NUMBER!*\n\n` +
            `🔢 Number: *${letter}-${number}*\n` +
            `📊 Total Called: *${calledNumbers.length}/75*\n\n` +
            `Check your cards with /mycards`;
        
        await notifyAllPlayers(playerMessage);
        
        logger.info(`Number ${number} called by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /call:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while calling number.');
    }
});

// Set game type (Admin only)
bot.onText(/\/settype (.+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const gameType = match[1].toLowerCase();

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    const validTypes = ['full house', '1 row', '1 column', '4 corners', 'x shape', 'random'];
    
    if (!validTypes.includes(gameType)) {
        return bot.sendMessage(chatId, 
            `❌ Invalid game type. Valid types:\n${validTypes.map(t => `• ${t}`).join('\n')}`
        );
    }

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Use /newgame to start one.');
        }

        await db.run('UPDATE games SET game_type = ? WHERE game_id = ?', [gameType, game.game_id]);

        await bot.sendMessage(chatId, `✅ Game type updated to: *${gameType}*`, { parse_mode: 'Markdown' });
        
        // Notify players
        await notifyAllPlayers(`🎮 Game type changed to: *${gameType}*`);
        
        logger.info(`Game type changed to ${gameType} by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /settype:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while setting game type.');
    }
});

// Set prize (Admin only)
bot.onText(/\/setprize (\d+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const prize = parseInt(match[1]);

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    if (prize < 100) {
        return bot.sendMessage(chatId, '❌ Prize must be at least 100 ETB.');
    }

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Use /newgame to start one.');
        }

        await db.run('UPDATE games SET prize_amount = ? WHERE game_id = ?', [prize, game.game_id]);

        await bot.sendMessage(chatId, `✅ Prize updated to: *${prize} ETB*`, { parse_mode: 'Markdown' });
        
        // Notify players
        await notifyAllPlayers(`💰 Game prize updated to: *${prize} ETB*`);
        
        logger.info(`Prize changed to ${prize} by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /setprize:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while setting prize.');
    }
});

// Set card price (Admin only)
bot.onText(/\/setprice (\d+)/, async (msg, match) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;
    const price = parseInt(match[1]);

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    if (price < 1) {
        return bot.sendMessage(chatId, '❌ Price must be at least 1 ETB.');
    }

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game. Use /newgame to start one.');
        }

        await db.run('UPDATE games SET card_price = ? WHERE game_id = ?', [price, game.game_id]);

        await bot.sendMessage(chatId, `✅ Card price updated to: *${price} ETB*`, { parse_mode: 'Markdown' });
        
        // Notify players
        await notifyAllPlayers(`💵 Card price updated to: *${price} ETB*`);
        
        logger.info(`Card price changed to ${price} by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /setprice:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while setting card price.');
    }
});

// End game (Admin only)
bot.onText(/\/endgame/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return bot.sendMessage(chatId, '❌ No active game.');
        }

        const winners = JSON.parse(game.winners);
        
        await db.run(
            'UPDATE games SET status = "ended", ended_at = ? WHERE game_id = ?',
            [new Date().toISOString(), game.game_id]
        );

        let message = `✅ *Game #${game.game_id} Ended*\n\n`;
        message += `📊 Total Called Numbers: ${JSON.parse(game.called_numbers).length}/75\n`;
        message += `🏆 Winners: ${winners.length}\n`;
        message += `👥 Total Players: ${game.total_players}\n`;
        message += `🃏 Total Cards: ${game.total_cards}\n`;
        
        if (winners.length > 0) {
            message += `💰 Total Prize Distributed: ${game.prize_amount} ETB\n`;
        } else {
            message += `❌ No winners this round!\n`;
        }

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
        
        await notifyAllUsers(`🎰 *GAME OVER!*\n\nGame #${game.game_id} has ended. Use /newgame to start a new round!`);
        
        logger.info(`Game ended by admin ${userId}`);
    } catch (error) {
        logger.error('Error in /endgame:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while ending game.');
    }
});

// Admin stats
bot.onText(/\/adminstats/, async (msg) => {
    const chatId = msg.chat.id;
    const userId = msg.from.id;

    if (!isAdmin(userId)) {
        return bot.sendMessage(chatId, '❌ Admin only command!');
    }

    try {
        const stats = await db.get(`
            SELECT 
                (SELECT COUNT(*) FROM users) as total_users,
                (SELECT COUNT(*) FROM games) as total_games,
                (SELECT COUNT(*) FROM cards) as total_cards,
                (SELECT COUNT(*) FROM transactions) as total_transactions,
                (SELECT SUM(amount) FROM transactions WHERE type = 'purchase') as total_revenue,
                (SELECT SUM(amount) FROM transactions WHERE type = 'win') as total_payouts,
                (SELECT COUNT(*) FROM games WHERE status = 'active') as active_games,
                (SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-1 day')) as active_today
        `);

        const profit = (stats.total_revenue || 0) - (stats.total_payouts || 0);

        let message = `📊 *Admin Statistics*\n\n`;
        message += `👥 Total Users: *${stats.total_users}*\n`;
        message += `📈 Active Today: *${stats.active_today}*\n`;
        message += `🎮 Total Games: *${stats.total_games}*\n`;
        message += `🃏 Total Cards: *${stats.total_cards}*\n`;
        message += `💳 Transactions: *${stats.total_transactions}*\n`;
        message += `💰 Total Revenue: *${stats.total_revenue || 0} ETB*\n`;
        message += `💸 Total Payouts: *${stats.total_payouts || 0} ETB*\n`;
        message += `📊 Profit: *${profit} ETB*\n`;
        message += `🎯 Active Games: *${stats.active_games}*`;

        await bot.sendMessage(chatId, message, { parse_mode: 'Markdown' });
    } catch (error) {
        logger.error('Error in /adminstats:', error);
        await bot.sendMessage(chatId, '❌ An error occurred while fetching admin stats.');
    }
});

// ==================== WEB INTERFACE ====================

// API endpoint for game stats
app.get('/api/stats', async (req, res) => {
    try {
        const game = await db.get('SELECT * FROM games WHERE status = "active" ORDER BY game_id DESC LIMIT 1');
        
        if (!game) {
            return res.json({ active: false });
        }

        const players = await db.all(
            'SELECT u.username, COUNT(c.card_id) as card_count FROM users u JOIN cards c ON u.user_id = c.user_id WHERE c.game_id = ? GROUP BY u.user_id',
            game.game_id
        );

        const stats = {
            active: true,
            game_id: game.game_id,
            game_type: game.game_type,
            prize_amount: game.prize_amount,
            card_price: game.card_price,
            called_numbers: JSON.parse(game.called_numbers),
            called_count: JSON.parse(game.called_numbers).length,
            winners: JSON.parse(game.winners),
            players: players,
            total_players: game.total_players,
            total_cards: game.total_cards
        };

        res.json(stats);
    } catch (error) {
        logger.error('API error:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// API endpoint for user stats
app.get('/api/user/:userId', async (req, res) => {
    try {
        const userId = req.params.userId;
        
        const user = await db.get(
            'SELECT user_id, username, balance, total_wins, total_cards_bought, total_spent, total_won, created_at, last_active FROM users WHERE user_id = ?',
            userId
        );
        
        if (!user) {
            return res.status(404).json({ error: 'User not found' });
        }

        const cards = await db.all(
            'SELECT COUNT(*) as total, SUM(CASE WHEN is_winner = 1 THEN 1 ELSE 0 END) as winners FROM cards WHERE user_id = ?',
            userId
        );

        const recentTransactions = await db.all(
            'SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
            userId
        );

        res.json({
            ...user,
            cards: cards[0],
            recent_transactions: recentTransactions
        });
    } catch (error) {
        logger.error('API error:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ 
        status: 'ok', 
        timestamp: new Date().toISOString(),
        bot: bot.isPolling() ? 'running' : 'stopped'
    });
});

// Start server
app.listen(PORT, () => {
    logger.info(`Web interface running on port ${PORT}`);
});

// ==================== INITIALIZE ====================

async function main() {
    try {
        await initializeDatabase();
        
        // Check if there's an active game, if not create one
        const activeGame = await db.get('SELECT * FROM games WHERE status = "active"');
        if (!activeGame) {
            await db.run(
                `INSERT INTO games 
                    (game_type, prize_amount, card_price, status, started_at) 
                VALUES (?, ?, ?, ?, ?)`,
                ['full house', 
                 parseInt(process.env.DEFAULT_PRIZE || 2000), 
                 parseInt(process.env.DEFAULT_CARD_PRICE || 10), 
                 'waiting', 
                 new Date().toISOString()]
            );
            logger.info('Created default waiting game');
        }
        
        logger.info('✅ Bot is running...');
        logger.info(`👑 Admin IDs: ${adminIds.join(', ')}`);
        
        // Set bot commands
        await bot.setMyCommands([
            { command: 'start', description: 'Start the bot' },
            { command: 'buy', description: 'Buy Bingo cards' },
            { command: 'mycards', description: 'View your cards' },
            { command: 'game', description: 'Current game status' },
            { command: 'winners', description: 'View winners' },
            { command: 'balance', description: 'Check balance' },
            { command: 'stats', description: 'Your statistics' },
            { command: 'players', description: 'Active players' }
        ]);
        
    } catch (error) {
        logger.error('❌ Failed to start bot:', error);
        process.exit(1);
    }
}

// Handle graceful shutdown
process.on('SIGINT', async () => {
    logger.info('Received SIGINT. Shutting down gracefully...');
    await db?.close();
    process.exit(0);
});

process.on('SIGTERM', async () => {
    logger.info('Received SIGTERM. Shutting down gracefully...');
    await db?.close();
    process.exit(0);
});

main().catch(console.error);