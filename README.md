# 🎰 MK BINGO TELEGRAM BOT

A full-featured multi-player Bingo game bot for Telegram with database support, admin controls, and real-time gameplay.

## ✨ Features

### 🎮 Game Features
- Multiple players support
- Buy up to 10 cards per transaction
- 5x5 Bingo cards with FREE space
- 6 different game types
- Automatic winner detection
- Real-time number calling
- Prize distribution to winners

### 🏆 Game Types
- **Full House** - All numbers marked
- **1 Row** - Complete any horizontal line
- **1 Column** - Complete any vertical line
- **4 Corners** - Mark all four corners
- **X Shape** - Mark both diagonals
- **Random** - Any of the above patterns

### 👤 Player Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome message and registration |
| `/buy [quantity]` | Buy Bingo cards (1-10 cards) |
| `/mycards` | View your current cards |
| `/game` | Current game status |
| `/winners` | View winners of current game |
| `/balance` | Check your balance |
| `/stats` | Your statistics |
| `/players` | See all active players |

### 👑 Admin Commands
| Command | Description |
|---------|-------------|
| `/newgame` | Start a new round |
| `/call` | Call next random number |
| `/settype [type]` | Set game type |
| `/setprize [amount]` | Set prize amount |
| `/setprice [amount]` | Set card price |
| `/endgame` | End current game |
| `/adminstats` | View bot statistics |

## 🚀 Installation

### Prerequisites
- Node.js 16+ 
- npm or yarn
- Telegram Bot Token (from @BotFather)

### Quick Setup

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/mk-bingo-bot.git
cd mk-bingo-bot