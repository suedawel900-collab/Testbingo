// js/player.js
import { database, ref, onValue, push, set, update, get, child } from './firebase-config.js';

// Player state
let playerId = localStorage.getItem('playerId') || 'player_' + Math.random().toString(36).substr(2, 9);
localStorage.setItem('playerId', playerId);

let playerBalance = 1000; // Default balance - in production, this would come from a database
let currentGame = null;
let autoCallInterval = null;
let selectedCards = [];
let playerCards = [];

// Initialize player dashboard
export function initPlayerDashboard() {
    // Save player ID
    localStorage.setItem('playerId', playerId);
    
    // Display player balance
    const balanceElement = document.getElementById('playerBalance');
    if (balanceElement) {
        balanceElement.textContent = `ብር: ${playerBalance}`;
    }
    
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
    
    if (currentGame && currentGame.status === 'active' && currentGame.players) {
        // Check if player is already in the game
        if (currentGame.players[playerId]) {
            document.getElementById('activeGameMessage').textContent = 'ቀድሞውንም ተቀላቅለዋል!';
            document.querySelector('#activeGameSection button').textContent = 'ወደ ጨዋታ ይግቡ';
        } else {
            document.getElementById('activeGameMessage').textContent = 'ንቁ ጨዋታ አለ!';
            document.querySelector('#activeGameSection button').textContent = 'ይቀላቀሉ';
        }
        activeGameSection.style.display = 'block';
    } else {
        activeGameSection.style.display = 'none';
    }
}

// Select cards function
export function selectCards() {
    const count = parseInt(document.getElementById('cardCount')?.value || '1');
    const pricePerCard = parseInt(document.getElementById('cardPrice')?.textContent || '10');
    const totalPrice = count * pricePerCard;
    
    if (playerBalance < totalPrice) {
        alert('በቂ ብር የለዎትም!');
        return;
    }
    
    // Save to localStorage and redirect
    localStorage.setItem('selectedCardCount', count);
    localStorage.setItem('totalPrice', totalPrice);
    localStorage.setItem('pricePerCard', pricePerCard);
    window.location.href = 'select-cards.html';
}

// Join active game
export function joinActiveGame() {
    window.location.href = 'game.html';
}

// Generate bingo cards for selection
export function generateCardSelection() {
    const cardCount = parseInt(localStorage.getItem('selectedCardCount') || '1');
    const pricePerCard = parseInt(localStorage.getItem('pricePerCard') || '10');
    const grid = document.getElementById('cardsGrid');
    if (!grid) return;
    
    grid.innerHTML = '';
    selectedCards = [];
    playerCards = [];
    
    // Update price display
    const priceDisplay = document.getElementById('cardPrice');
    if (priceDisplay) {
        priceDisplay.textContent = pricePerCard;
    }
    
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
    playerCards[index] = numbers; // Store card numbers
    
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
            const displayNum = num || 'FREE';
            const cellClass = num ? 'bingo-cell' : 'bingo-cell free';
            html += `<div class="${cellClass}">${displayNum}</div>`;
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
    const usedNumbers = new Set();
    
    for (let row = 0; row < 5; row++) {
        const rowNumbers = [];
        for (let col = 0; col < 5; col++) {
            if (row === 2 && col === 2) {
                rowNumbers.push(null); // FREE space
            } else {
                const min = col * 15 + 1;
                const max = (col + 1) * 15;
                let num;
                do {
                    num = Math.floor(Math.random() * (max - min + 1)) + min;
                } while (usedNumbers.has(num)); // Ensure unique numbers per column
                usedNumbers.add(num);
                rowNumbers.push(num);
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
        selectedCards.sort((a, b) => a - b).forEach(index => {
            cards.push(playerCards[index]);
        });
        
        // Save to database
        await set(gameRef, {
            cards: cards,
            balance: parseInt(localStorage.getItem('totalPrice')),
            joinedAt: Date.now(),
            status: 'active',
            markedNumbers: []
        });
        
        // Deduct from player balance (in production, this would be handled by a payment system)
        playerBalance -= parseInt(localStorage.getItem('totalPrice'));
        
        // Redirect to game
        window.location.href = 'game.html';
    } catch (error) {
        console.error('Error confirming selection:', error);
        alert('ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።');
    }
}

// Initialize game page
export function initGame() {
    // Check if player has cards
    get(child(ref(database), `activeGame/players/${playerId}`)).then((snapshot) => {
        if (!snapshot.exists()) {
            alert('እባክዎ መጀመሪያ ካርዶችን ይምረጡ!');
            window.location.href = 'dashboard.html';
            return;
        }
    });
    
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
            lastNumberElement.textContent = game.calledNumbers[game.calledNumbers.length - 1];
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
                const displayNum = num === 'FREE' ? 'FREE' : num;
                html += `<div class="${className}">${displayNum}</div>`;
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
    if (currentGame && currentGame.status === 'active' && !currentGame.winners) {
        const newNumber = Math.floor(Math.random() * 75) + 1;
        
        // Check if number is new
        if (!currentGame.calledNumbers || !currentGame.calledNumbers.includes(newNumber)) {
            const updates = {};
            const calledNumbers = currentGame.calledNumbers || [];
            calledNumbers.push(newNumber);
            
            updates['activeGame/calledNumbers'] = calledNumbers;
            updates['activeGame/lastCalledAt'] = Date.now();
            
            update(ref(database), updates).catch(error => {
                console.error('Error calling number:', error);
            });
        } else {
            // Try another number
            callNumber();
        }
    }
}

// Check for bingo
export function checkBingo() {
    if (!currentGame) {
        alert('ጨዋታ አልተገኘም');
        return;
    }
    
    if (currentGame.winners) {
        alert('ጨዋታው አልቋል!');
        return;
    }
    
    const playerCards = currentGame.players[playerId].cards;
    const calledNumbers = currentGame.calledNumbers || [];
    const gameType = currentGame.settings?.gameType || 'fullhouse';
    
    // Check each card for bingo
    for (let cardIndex = 0; cardIndex < playerCards.length; cardIndex++) {
        const result = checkCardForBingo(playerCards[cardIndex], calledNumbers, gameType);
        
        if (result.isBingo) {
            // Check if already claimed
            if (currentGame.bingoClaims) {
                const claims = Object.values(currentGame.bingoClaims);
                const alreadyClaimed = claims.some(claim => 
                    claim.playerId === playerId && claim.cardIndex === cardIndex
                );
                
                if (alreadyClaimed) {
                    alert('ይህን ካርድ ቀድመው አስመዝግበዋል!');
                    return;
                }
            }
            
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
                    alert('ቢንጎ! ጥያቄዎ ተልኳል። እባክዎ ይጠብቁ...');
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
    
    // Check four corners
    if (gameType === 'fourcorners') {
        const corners = [
            card[0][0], card[0][4],
            card[4][0], card[4][4]
        ];
        
        let cornersComplete = true;
        for (let corner of corners) {
            if (corner !== 'FREE' && !calledNumbers.includes(corner)) {
                cornersComplete = false;
                break;
            }
        }
        
        if (cornersComplete) {
            return { isBingo: true, type: 'fourcorners', numbers: corners };
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
                <h3>አሸናፊ: ${winner.playerId.substring(0, 8)}...</h3>
                <p>አሸናፊ ካርድ: ${winner.cardIndex + 1}</p>
                <p>አሸናፊ አይነት: ${winner.type}</p>
                <p>ሽልማት: ${winner.prize.toFixed(2)} ብር</p>
            </div>
        `;
    });
    html += '</div>';
    
    // Show winning cards if available
    if (game.winningCards && game.winningCards.length > 0) {
        html += '<h3>አሸናፊ ካርዶች:</h3>';
        html += '<div class="winning-cards">';
        
        game.winningCards.forEach((winCard, idx) => {
            html += `<div class="winning-card">`;
            html += `<h4>ካርድ ${idx + 1}</h4>`;
            html += '<div class="mini-card">';
            winCard.card.forEach(row => {
                html += '<div class="mini-row">';
                row.forEach(num => {
                    const displayNum = num === 'FREE' ? 'F' : num;
                    const isCalled = game.calledNumbers?.includes(num);
                    const cellClass = isCalled ? 'mini-cell called' : 'mini-cell';
                    html += `<span class="${cellClass}">${displayNum}</span>`;
                });
                html += '</div>';
            });
            html += '</div>';
            html += `<p class="win-type">${winCard.type}</p>`;
            html += '</div>';
        });
        
        html += '</div>';
    }
    
    winnerInfo.innerHTML = html;
    modal.style.display = 'block';
    
    // Disable bingo button
    const bingoBtn = document.getElementById('bingoBtn');
    if (bingoBtn) {
        bingoBtn.disabled = true;
    }
}

// Close winners modal
export function closeWinnerModal() {
    const modal = document.getElementById('winnerModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Add money to player balance (for testing)
export function addMoney(amount) {
    playerBalance += amount;
    const balanceElement = document.getElementById('playerBalance');
    if (balanceElement) {
        balanceElement.textContent = `ብር: ${playerBalance}`;
    }
    alert(`${amount} ብር ተጨምሯል! አሁን ያለው ብር: ${playerBalance}`);
}

// Initialize based on current page
document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    
    if (path.includes('dashboard.html') || path.endsWith('player/')) {
        initPlayerDashboard();
    } else if (path.includes('select-cards.html')) {
        generateCardSelection();
    } else if (path.includes('game.html')) {
        initGame();
    }
});