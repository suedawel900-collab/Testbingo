// js/player.js
import { database, ref, onValue, push, set, update, get, child } from './firebase-config.js';

// Player state
let playerId = localStorage.getItem('playerId') || 'player_' + Math.random().toString(36).substr(2, 9);
localStorage.setItem('playerId', playerId);

let playerBalance = 1000; // Default balance
let currentGame = null;
let autoCallInterval = null;
let selectedCards = [];
let playerCards = [];

// Initialize player dashboard
export function initPlayerDashboard() {
    // Save player ID
    localStorage.setItem('playerId', playerId);
    
    // Listen for game settings
    onValue(ref(database, 'gameSettings'), (snapshot) => {
        const settings = snapshot.val() || {};
        updatePriceDisplay(settings);
    });
    
    // Listen for active game
    onValue(ref(database, 'activeGame'), (snapshot) => {
        currentGame = snapshot.val();
        checkActiveGame();
    });
    
    // Update total price on card count change
    const cardCountInput = document.getElementById('cardCount');
    if (cardCountInput) {
        cardCountInput.addEventListener('input', updateTotalPrice);
    }
}

// Update price displays
function updatePriceDisplay(settings) {
    const cardPriceElement = document.getElementById('cardPrice');
    if (cardPriceElement) {
        cardPriceElement.textContent = settings.cardPrice || 10;
    }
    updateTotalPrice();
}

// Calculate total price
function updateTotalPrice() {
    const count = document.getElementById('cardCount')?.value || 1;
    const price = document.getElementById('cardPrice')?.textContent || 10;
    const totalPriceElement = document.getElementById('totalPrice');
    if (totalPriceElement) {
        totalPriceElement.textContent = count * price;
    }
}

// Check if there's an active game
function checkActiveGame() {
    const activeGameSection = document.getElementById('activeGameSection');
    if (!activeGameSection) return;
    
    if (currentGame && currentGame.status === 'active') {
        activeGameSection.style.display = 'block';
    } else {
        activeGameSection.style.display = 'none';
    }
}

// Select cards function
export function selectCards() {
    const count = document.getElementById('cardCount')?.value;
    const totalPrice = parseInt(document.getElementById('totalPrice')?.textContent || '0');
    
    if (playerBalance < totalPrice) {
        alert('በቂ ብር የለዎትም!');
        return;
    }
    
    // Save to localStorage and redirect
    localStorage.setItem('selectedCardCount', count);
    localStorage.setItem('totalPrice', totalPrice);
    window.location.href = 'select-cards.html';
}

// Join active game
export function joinActiveGame() {
    window.location.href = 'game.html';
}

// Generate bingo cards for selection
export function generateCardSelection() {
    const cardCount = localStorage.getItem('selectedCardCount');
    const grid = document.getElementById('cardsGrid');
    if (!grid) return;
    
    grid.innerHTML = '';
    selectedCards = [];
    
    for (let i = 0; i < cardCount; i++) {
        const card = createBingoCard(i, true);
        grid.appendChild(card);
    }
    
    updateSelectionDisplay();
}

// Create a bingo card element
function createBingoCard(index, selectable = false) {
    const card = document.createElement('div');
    card.className = 'bingo-card';
    card.dataset.index = index;
    
    const numbers = generateBingoNumbers();
    
    let html = `<div class="bingo-card-header">ካርድ ${index + 1}</div>`;
    html += '<div class="bingo-card-body">';
    
    // B I N G O headers
    html += '<div class="bingo-row header">';
    ['B', 'I', 'N', 'G', 'O'].forEach(letter => {
        html += `<div class="bingo-cell header">${letter}</div>`;
    });
    html += '</div>';
    
    // Numbers
    for (let row = 0; row < 5; row++) {
        html += '<div class="bingo-row">';
        for (let col = 0; col < 5; col++) {
            const num = numbers[row][col];
            html += `<div class="bingo-cell">${num || 'FREE'}</div>`;
        }
        html += '</div>';
    }
    
    html += '</div>';
    
    if (selectable) {
        html += '<div class="bingo-card-footer">';
        html += `<input type="checkbox" class="card-select" data-card-index="${index}">`;
        html += '<label>ይምረጡ</label>';
        html += '</div>';
    }
    
    card.innerHTML = html;
    
    // Add selection handler if selectable
    if (selectable) {
        const checkbox = card.querySelector('.card-select');
        checkbox.addEventListener('change', function(e) {
            if (this.checked) {
                selectedCards.push(index);
                // Store card numbers
                if (!playerCards[index]) {
                    playerCards[index] = numbers;
                }
            } else {
                selectedCards = selectedCards.filter(i => i !== index);
            }
            updateSelectionDisplay();
        });
    }
    
    return card;
}

// Generate random bingo numbers
function generateBingoNumbers() {
    const numbers = [];
    for (let row = 0; row < 5; row++) {
        const rowNumbers = [];
        for (let col = 0; col < 5; col++) {
            if (row === 2 && col === 2) {
                rowNumbers.push(null); // FREE space
            } else {
                const min = col * 15 + 1;
                const max = (col + 1) * 15;
                rowNumbers.push(Math.floor(Math.random() * (max - min + 1)) + min);
            }
        }
        numbers.push(rowNumbers);
    }
    return numbers;
}

// Update selection display
function updateSelectionDisplay() {
    const selectedCountElement = document.getElementById('selectedCount');
    const totalPriceElement = document.getElementById('totalPrice');
    const confirmBtn = document.getElementById('confirmBtn');
    
    if (selectedCountElement) {
        selectedCountElement.textContent = selectedCards.length;
    }
    
    if (totalPriceElement) {
        const pricePerCard = parseInt(document.getElementById('cardPrice')?.textContent || '10');
        totalPriceElement.textContent = selectedCards.length * pricePerCard;
    }
    
    if (confirmBtn) {
        confirmBtn.disabled = selectedCards.length === 0;
    }
}

// Confirm card selection and pay
export async function confirmSelection() {
    if (selectedCards.length === 0) return;
    
    try {
        const gameRef = ref(database, 'activeGame/players/' + playerId);
        
        // Get selected cards
        const cards = [];
        document.querySelectorAll('.bingo-card').forEach((card, idx) => {
            if (selectedCards.includes(idx)) {
                const cardNumbers = [];
                const rows = card.querySelectorAll('.bingo-row:not(.header)');
                rows.forEach(row => {
                    const rowNumbers = [];
                    row.querySelectorAll('.bingo-cell').forEach(cell => {
                        const text = cell.textContent;
                        rowNumbers.push(text === 'FREE' ? 'FREE' : parseInt(text));
                    });
                    cardNumbers.push(rowNumbers);
                });
                cards.push(cardNumbers);
            }
        });
        
        // Save to database
        await set(gameRef, {
            cards: cards,
            balance: parseInt(localStorage.getItem('totalPrice')),
            joinedAt: Date.now(),
            status: 'active',
            markedNumbers: []
        });
        
        // Redirect to game
        window.location.href = 'game.html';
    } catch (error) {
        console.error('Error confirming selection:', error);
        alert('ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።');
    }
}

// Initialize game page
export function initGame() {
    // Listen for game updates
    onValue(ref(database, 'activeGame'), (snapshot) => {
        const game = snapshot.val();
        if (game) {
            currentGame = game;
            updateGameDisplay(game);
            
            // Show winners if any
            if (game.winners && game.winners.length > 0) {
                showWinners(game);
            }
        }
    });
    
    // Auto-call toggle
    const autoCallCheckbox = document.getElementById('autoCall');
    if (autoCallCheckbox) {
        autoCallCheckbox.addEventListener('change', handleAutoCall);
    }
}

// Update game display
function updateGameDisplay(game) {
    // Update called numbers
    if (game.calledNumbers) {
        const calledNumbersElement = document.getElementById('calledNumbers');
        if (calledNumbersElement) {
            calledNumbersElement.innerHTML = 'የተጠሩ ቁጥሮች: ' + game.calledNumbers.join(', ');
        }
        
        const lastNumberElement = document.getElementById('lastNumber');
        if (lastNumberElement && game.calledNumbers.length > 0) {
            lastNumberElement.textContent = 'የመጨረሻ ቁጥር: ' + game.calledNumbers[game.calledNumbers.length - 1];
        }
    }
    
    // Display player cards
    if (game.players && game.players[playerId]) {
        displayPlayerCards(game.players[playerId].cards, game.calledNumbers || []);
    }
}

// Display player's cards
function displayPlayerCards(cards, calledNumbers) {
    const container = document.getElementById('playerCards');
    if (!container) return;
    
    container.innerHTML = '';
    
    cards.forEach((card, index) => {
        const cardElement = document.createElement('div');
        cardElement.className = 'bingo-card player-card';
        
        let html = `<div class="bingo-card-header">ካርድ ${index + 1}</div>`;
        html += '<div class="bingo-card-body">';
        
        // Headers
        html += '<div class="bingo-row header">';
        ['B', 'I', 'N', 'G', 'O'].forEach(letter => {
            html += `<div class="bingo-cell header">${letter}</div>`;
        });
        html += '</div>';
        
        // Numbers
        card.forEach(row => {
            html += '<div class="bingo-row">';
            row.forEach(num => {
                const isMarked = num === 'FREE' || calledNumbers.includes(num);
                const className = isMarked ? 'bingo-cell marked' : 'bingo-cell';
                html += `<div class="${className}">${num || 'FREE'}</div>`;
            });
            html += '</div>';
        });
        
        html += '</div>';
        cardElement.innerHTML = html;
        container.appendChild(cardElement);
    });
}

// Handle auto-call toggle
function handleAutoCall(event) {
    if (event.target.checked) {
        // Auto-call every 3 seconds
        autoCallInterval = setInterval(() => {
            if (currentGame && currentGame.status === 'active' && !currentGame.winners) {
                callNumber();
            }
        }, 3000);
    } else {
        clearInterval(autoCallInterval);
    }
}

// Call a number
export function callNumber() {
    if (currentGame && currentGame.status === 'active') {
        const newNumber = generateRandomNumber();
        
        // Check if number is new
        if (!currentGame.calledNumbers || !currentGame.calledNumbers.includes(newNumber)) {
            const updates = {};
            const calledNumbers = currentGame.calledNumbers || [];
            calledNumbers.push(newNumber);
            
            updates['activeGame/calledNumbers'] = calledNumbers;
            
            update(ref(database), updates).catch(error => {
                console.error('Error calling number:', error);
            });
        }
    }
}

// Generate random number between 1-75
function generateRandomNumber() {
    return Math.floor(Math.random() * 75) + 1;
}

// Check for bingo
export function checkBingo() {
    if (!currentGame) return;
    
    const playerCards = currentGame.players[playerId].cards;
    const calledNumbers = currentGame.calledNumbers || [];
    const gameType = currentGame.settings?.gameType || 'fullhouse';
    
    // Check each card for bingo
    for (let cardIndex = 0; cardIndex < playerCards.length; cardIndex++) {
        const result = checkCardForBingo(playerCards[cardIndex], calledNumbers, gameType);
        
        if (result.isBingo) {
            // Submit bingo claim
            const bingoData = {
                playerId: playerId,
                cardIndex: cardIndex,
                type: result.type,
                timestamp: Date.now(),
                numbers: result.numbers || []
            };
            
            const bingoRef = push(ref(database, 'activeGame/bingoClaims'));
            set(bingoRef, bingoData)
                .then(() => {
                    alert('ቢንጎ! ጥያቄዎ ተልኳል።');
                })
                .catch(error => {
                    console.error('Error submitting bingo:', error);
                    alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
                });
            
            return;
        }
    }
    
    alert('ቢንጎ የለም! ትክክለኛዎቹን ቁጥሮች ይጠብቁ።');
}

// Check if a card has bingo
function checkCardForBingo(card, calledNumbers, gameType) {
    // Check rows
    for (let row = 0; row < 5; row++) {
        let rowComplete = true;
        const rowNumbers = [];
        for (let col = 0; col < 5; col++) {
            const num = card[row][col];
            rowNumbers.push(num);
            if (num !== 'FREE' && !calledNumbers.includes(num)) {
                rowComplete = false;
                break;
            }
        }
        if (rowComplete) {
            return { isBingo: true, type: 'row', numbers: rowNumbers };
        }
    }
    
    // Check columns
    for (let col = 0; col < 5; col++) {
        let colComplete = true;
        const colNumbers = [];
        for (let row = 0; row < 5; row++) {
            const num = card[row][col];
            colNumbers.push(num);
            if (num !== 'FREE' && !calledNumbers.includes(num)) {
                colComplete = false;
                break;
            }
        }
        if (colComplete) {
            return { isBingo: true, type: 'column', numbers: colNumbers };
        }
    }
    
    // Check diagonals
    let diag1Complete = true;
    let diag2Complete = true;
    const diag1Numbers = [];
    const diag2Numbers = [];
    
    for (let i = 0; i < 5; i++) {
        const num1 = card[i][i];
        const num2 = card[i][4 - i];
        
        diag1Numbers.push(num1);
        diag2Numbers.push(num2);
        
        if (num1 !== 'FREE' && !calledNumbers.includes(num1)) diag1Complete = false;
        if (num2 !== 'FREE' && !calledNumbers.includes(num2)) diag2Complete = false;
    }
    
    if (diag1Complete) {
        return { isBingo: true, type: 'diagonal', numbers: diag1Numbers };
    }
    if (diag2Complete) {
        return { isBingo: true, type: 'diagonal', numbers: diag2Numbers };
    }
    
    // Check full house if game type is fullhouse
    if (gameType === 'fullhouse') {
        let fullHouseComplete = true;
        const allNumbers = [];
        
        for (let row of card) {
            for (let num of row) {
                allNumbers.push(num);
                if (num !== 'FREE' && !calledNumbers.includes(num)) {
                    fullHouseComplete = false;
                    break;
                }
            }
        }
        
        if (fullHouseComplete) {
            return { isBingo: true, type: 'fullhouse', numbers: allNumbers };
        }
    }
    
    return { isBingo: false };
}

// Show winners modal
function showWinners(game) {
    const modal = document.getElementById('winnerModal');
    const winnerInfo = document.getElementById('winnerInfo');
    
    if (!modal || !winnerInfo) return;
    
    let html = '<div class="winners-list">';
    game.winners.forEach(winner => {
        html += `
            <div class="winner-item">
                <h3>አሸናፊ: ${winner.playerId}</h3>
                <p>አሸናፊ ካርድ: ${winner.cardIndex + 1}</p>
                <p>አሸናፊ አይነት: ${winner.type}</p>
                <p>ሽልማት: ${winner.prize} ብር</p>
            </div>
        `;
    });
    html += '</div>';
    
    // Show winning cards if available
    if (game.winningCards) {
        html += '<h3>አሸናፊ ካርዶች:</h3>';
        game.winningCards.forEach((winCard, idx) => {
            html += `<div class="winning-card">`;
            html += `<h4>ካርድ ${idx + 1}</h4>`;
            html += '<div class="mini-card">';
            winCard.card.forEach(row => {
                html += '<div class="mini-row">';
                row.forEach(num => {
                    html += `<span class="mini-cell ${num === 'FREE' ? 'free' : ''}">${num || 'F'}</span>`;
                });
                html += '</div>';
            });
            html += '</div></div>';
        });
    }
    
    winnerInfo.innerHTML = html;
    modal.style.display = 'block';
}

// Close winners modal
export function closeWinnerModal() {
    const modal = document.getElementById('winnerModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Initialize based on current page
document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    
    if (path.includes('dashboard.html')) {
        initPlayerDashboard();
    } else if (path.includes('select-cards.html')) {
        generateCardSelection();
        
        // Get price from localStorage or settings
        const pricePerCard = 10; // Default
        document.getElementById('cardPrice').textContent = pricePerCard;
    } else if (path.includes('game.html')) {
        initGame();
    }
});