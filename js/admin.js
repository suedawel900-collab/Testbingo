// js/admin.js
import { database, ref, onValue, set, update, get, remove } from './firebase-config.js';

// Admin state
let currentGame = null;
let autoSettingsTimer = null;
let bingoClaims = {};

// Initialize admin dashboard
export function initAdminDashboard() {
    console.log('Admin dashboard initializing...');
    
    // Listen for game settings
    onValue(ref(database, 'gameSettings'), (snapshot) => {
        const settings = snapshot.val();
        if (settings) {
            updateSettingsForm(settings);
        } else {
            // Initialize default settings if none exist
            initializeDefaultSettings();
        }
    });
    
    // Listen for active game
    onValue(ref(database, 'activeGame'), (snapshot) => {
        currentGame = snapshot.val();
        updateDashboardDisplay();
    });
    
    // Listen for bingo claims
    onValue(ref(database, 'activeGame/bingoClaims'), (snapshot) => {
        bingoClaims = snapshot.val() || {};
        if (currentGame) {
            checkBingoClaims(currentGame);
        }
    });
    
    // Setup auto-refresh for game status every 5 seconds
    setInterval(() => {
        if (currentGame) {
            updateGameStatus(currentGame);
        }
    }, 5000);
}

// Initialize default settings
function initializeDefaultSettings() {
    const defaultSettings = {
        cardPrice: 10,
        gameType: 'fullhouse',
        prizeAmount: 20,
        lastUpdated: Date.now(),
        initialized: true
    };
    
    set(ref(database, 'gameSettings'), defaultSettings)
        .then(() => {
            console.log('Default settings initialized');
        })
        .catch(error => {
            console.error('Error initializing settings:', error);
        });
}

// Update dashboard display
function updateDashboardDisplay() {
    if (currentGame) {
        displayActivePlayers(currentGame.players);
        updateGameStatus(currentGame);
        displayCalledNumbers(currentGame.calledNumbers);
    } else {
        document.getElementById('activePlayers').innerHTML = '<p class="no-data">ንቁ ጨዋታ የለም</p>';
        document.getElementById('bingoClaims').innerHTML = '<p class="no-data">ምንም የቢንጎ ጥያቄ የለም</p>';
        document.getElementById('calledNumbers').innerHTML = '<p class="no-data">ምንም የተጠሩ ቁጥሮች የሉም</p>';
        
        const statusContainer = document.getElementById('gameStatus');
        if (statusContainer) {
            statusContainer.innerHTML = '<div class="status-item">ሁኔታ: ጨዋታ የለም</div>';
        }
    }
}

// Update settings form
function updateSettingsForm(settings) {
    const cardPriceInput = document.getElementById('cardPrice');
    const gameTypeSelect = document.getElementById('gameType');
    const prizeAmountInput = document.getElementById('prizeAmount');
    
    if (cardPriceInput) cardPriceInput.value = settings.cardPrice || 10;
    if (gameTypeSelect) gameTypeSelect.value = settings.gameType || 'fullhouse';
    if (prizeAmountInput) prizeAmountInput.value = settings.prizeAmount || 20;
    
    // Update last updated display
    const lastUpdatedElement = document.getElementById('lastUpdated');
    if (lastUpdatedElement && settings.lastUpdated) {
        const date = new Date(settings.lastUpdated);
        lastUpdatedElement.textContent = `መጨረሻ የተሻሻለ: ${date.toLocaleString()}`;
    }
}

// Save game settings
export function saveSettings() {
    const cardPrice = parseInt(document.getElementById('cardPrice')?.value || '10');
    const gameType = document.getElementById('gameType')?.value || 'fullhouse';
    const prizeAmount = parseInt(document.getElementById('prizeAmount')?.value || '20');
    
    // Validate inputs
    if (cardPrice < 1) {
        alert('የካርድ ዋጋ ከ0 በላይ መሆን አለበት');
        return;
    }
    
    if (prizeAmount < 1) {
        alert('የሽልማት መጠን ከ0 በላይ መሆን አለበት');
        return;
    }
    
    const settings = {
        cardPrice: cardPrice,
        gameType: gameType,
        prizeAmount: prizeAmount,
        lastUpdated: Date.now(),
        updatedBy: 'admin'
    };
    
    set(ref(database, 'gameSettings'), settings)
        .then(() => {
            alert('ቅንብሮች ተቀምጠዋል!');
            
            // Clear auto-settings timer if it exists
            if (autoSettingsTimer) {
                clearTimeout(autoSettingsTimer);
                autoSettingsTimer = null;
            }
        })
        .catch(error => {
            console.error('Error saving settings:', error);
            alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
        });
}

// Start new game
export function startNewGame() {
    // Clear any existing timer
    if (autoSettingsTimer) {
        clearTimeout(autoSettingsTimer);
    }
    
    // Get current settings
    const cardPrice = parseInt(document.getElementById('cardPrice')?.value || '10');
    const gameType = document.getElementById('gameType')?.value || 'fullhouse';
    const prizeAmount = parseInt(document.getElementById('prizeAmount')?.value || '20');
    
    const gameSettings = {
        status: 'active',
        startTime: Date.now(),
        calledNumbers: [],
        players: {},
        winners: null,
        bingoClaims: {},
        settings: {
            cardPrice: cardPrice,
            gameType: gameType,
            prizeAmount: prizeAmount
        },
        createdAt: Date.now(),
        createdBy: 'admin'
    };
    
    set(ref(database, 'activeGame'), gameSettings)
        .then(() => {
            alert('አዲስ ጨዋታ ተጀምሯል!');
            
            // Set auto-settings timer (15 seconds)
            autoSettingsTimer = setTimeout(() => {
                setDefaultSettings();
            }, 15000);
            
            // Log game start
            console.log('New game started with settings:', gameSettings);
        })
        .catch(error => {
            console.error('Error starting game:', error);
            alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
        });
}

// Set default settings after timeout
function setDefaultSettings() {
    const defaultSettings = {
        cardPrice: 10,
        gameType: 'random',
        prizeAmount: 20,
        lastUpdated: Date.now(),
        autoSet: true,
        reason: 'Admin timeout - 15 seconds passed'
    };
    
    set(ref(database, 'gameSettings'), defaultSettings)
        .then(() => {
            console.log('Default settings applied after timeout');
            
            // Update the form
            updateSettingsForm(defaultSettings);
            
            // Show notification to admin
            showNotification('ከ15 ሰከንድ በኋላ ቅንብሮች ወደ ነባሪ ተቀይረዋል (10 ብር፣ ራንደም)', 'warning');
        })
        .catch(error => {
            console.error('Error setting default settings:', error);
        });
}

// Show notification
function showNotification(message, type = 'info') {
    const notificationArea = document.getElementById('notificationArea');
    if (!notificationArea) return;
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    notificationArea.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

// End current game
export function endGame() {
    if (autoSettingsTimer) {
        clearTimeout(autoSettingsTimer);
    }
    
    if (!currentGame) {
        alert('ንቁ ጨዋታ የለም');
        return;
    }
    
    if (confirm('እርግጠኛ ነዎት ጨዋታውን ማቆም ይፈልጋሉ?')) {
        // Archive the game before deleting
        archiveGame(currentGame);
        
        set(ref(database, 'activeGame'), null)
            .then(() => {
                alert('ጨዋታ ተቋርጧል');
            })
            .catch(error => {
                console.error('Error ending game:', error);
                alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
            });
    }
}

// Archive game for history
function archiveGame(game) {
    const archiveRef = ref(database, `gameHistory/${Date.now()}`);
    set(archiveRef, {
        ...game,
        archivedAt: Date.now()
    }).catch(error => {
        console.error('Error archiving game:', error);
    });
}

// Display active players
function displayActivePlayers(players) {
    const container = document.getElementById('activePlayers');
    if (!container) return;
    
    if (!players || Object.keys(players).length === 0) {
        container.innerHTML = '<p class="no-data">ምንም ተጫዋች የለም</p>';
        return;
    }
    
    let html = '<h3>📋 ተጫዋቾች ዝርዝር</h3>';
    html += '<div class="players-grid">';
    
    Object.entries(players).forEach(([playerId, playerData]) => {
        const joinTime = new Date(playerData.joinedAt).toLocaleTimeString();
        const cardCount = playerData.cards?.length || 0;
        
        html += `
            <div class="player-card-mini" onclick="viewPlayerCards('${playerId}')">
                <div class="player-id">🆔 ${playerId.substring(0, 8)}...</div>
                <div class="player-cards-count">🎫 ${cardCount} ካርዶች</div>
                <div class="player-joined">⏰ ${joinTime}</div>
                <button class="btn-small" onclick="event.stopPropagation(); viewPlayerCards('${playerId}')">ካርዶች ይመልከቱ</button>
            </div>
        `;
    });
    
    html += '</div>';
    container.innerHTML = html;
}

// View player cards
window.viewPlayerCards = function(playerId) {
    if (!currentGame || !currentGame.players[playerId]) return;
    
    const player = currentGame.players[playerId];
    const cards = player.cards;
    const calledNumbers = currentGame.calledNumbers || [];
    
    let modalHtml = '<div class="player-cards-modal">';
    modalHtml += `<h2>የተጫዋች ካርዶች: ${playerId.substring(0, 8)}...</h2>`;
    
    cards.forEach((card, index) => {
        modalHtml += `<h3>ካርድ ${index + 1}</h3>`;
        modalHtml += '<div class="mini-card">';
        card.forEach(row => {
            modalHtml += '<div class="mini-row">';
            row.forEach(num => {
                const isCalled = num === 'FREE' || calledNumbers.includes(num);
                const cellClass = isCalled ? 'mini-cell called' : 'mini-cell';
                const displayNum = num === 'FREE' ? 'F' : num;
                modalHtml += `<span class="${cellClass}">${displayNum}</span>`;
            });
            modalHtml += '</div>';
        });
        modalHtml += '</div>';
    });
    
    modalHtml += '<button onclick="closePlayerCardsModal()" class="btn btn-primary">ዝጋ</button>';
    modalHtml += '</div>';
    
    // Create and show modal
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'playerCardsModal';
    modal.innerHTML = modalHtml;
    document.body.appendChild(modal);
}

// Close player cards modal
window.closePlayerCardsModal = function() {
    const modal = document.getElementById('playerCardsModal');
    if (modal) {
        modal.remove();
    }
}

// Display called numbers
function displayCalledNumbers(calledNumbers) {
    const container = document.getElementById('calledNumbers');
    if (!container) return;
    
    if (!calledNumbers || calledNumbers.length === 0) {
        container.innerHTML = '<p class="no-data">ምንም የተጠሩ ቁጥሮች የሉም</p>';
        return;
    }
    
    let html = '<h3>🔢 የተጠሩ ቁጥሮች</h3>';
    html += '<div class="called-numbers-grid">';
    
    calledNumbers.forEach((num, index) => {
        const isLast = index === calledNumbers.length - 1;
        html += `<span class="called-number ${isLast ? 'last-called' : ''}">${num}</span>`;
    });
    
    html += '</div>';
    html += `<p class="total-called">ጠቅላላ: ${calledNumbers.length} ቁጥሮች</p>`;
    
    container.innerHTML = html;
}

// Update game status display
function updateGameStatus(game) {
    const statusContainer = document.getElementById('gameStatus');
    if (!statusContainer) return;
    
    const calledCount = game.calledNumbers?.length || 0;
    const playerCount = game.players ? Object.keys(game.players).length : 0;
    const gameType = game.settings?.gameType || 'fullhouse';
    const cardPrice = game.settings?.cardPrice || 10;
    const prizeAmount = game.settings?.prizeAmount || 20;
    
    // Calculate game duration
    let duration = '0 ደቂቃ';
    if (game.startTime) {
        const minutes = Math.floor((Date.now() - game.startTime) / 60000);
        duration = `${minutes} ደቂቃ`;
    }
    
    statusContainer.innerHTML = `
        <div class="status-header">📊 የጨዋታ ሁኔታ</div>
        <div class="status-grid">
            <div class="status-item">
                <span class="status-label">ሁኔታ:</span>
                <span class="status-value ${game.status}">${game.status === 'active' ? 'ንቁ' : 'ተጠናቋል'}</span>
            </div>
            <div class="status-item">
                <span class="status-label">የተጠሩ ቁጥሮች:</span>
                <span class="status-value">${calledCount}</span>
            </div>
            <div class="status-item">
                <span class="status-label">ተጫዋቾች:</span>
                <span class="status-value">${playerCount}</span>
            </div>
            <div class="status-item">
                <span class="status-label">የጨዋታ አይነት:</span>
                <span class="status-value">${getGameTypeName(gameType)}</span>
            </div>
            <div class="status-item">
                <span class="status-label">የካርድ ዋጋ:</span>
                <span class="status-value">${cardPrice} ብር</span>
            </div>
            <div class="status-item">
                <span class="status-label">ሽልማት:</span>
                <span class="status-value">${prizeAmount} ብር</span>
            </div>
            <div class="status-item">
                <span class="status-label">የቆይታ ጊዜ:</span>
                <span class="status-value">${duration}</span>
            </div>
        </div>
    `;
}

// Get game type name in Amharic
function getGameTypeName(type) {
    const names = {
        'fullhouse': 'ሙሉ ካርድ',
        'row': 'አንድ ረድፍ',
        'column': 'አንድ አምድ',
        'diagonal': 'ዲያግናል',
        'fourcorners': 'አራት ማዕዘን',
        'random': 'ራንደም'
    };
    return names[type] || type;
}

// Check bingo claims
function checkBingoClaims(game) {
    const container = document.getElementById('bingoClaims');
    if (!container) return;
    
    if (!game.bingoClaims || Object.keys(game.bingoClaims).length === 0) {
        container.innerHTML = '<p class="no-data">ምንም የቢንጎ ጥያቄ የለም</p>';
        return;
    }
    
    const claims = Object.entries(game.bingoClaims).map(([id, claim]) => ({
        id,
        ...claim
    }));
    
    const validWinners = [];
    
    claims.forEach(claim => {
        if (game.players && game.players[claim.playerId]) {
            const playerCards = game.players[claim.playerId].cards;
            if (playerCards && playerCards[claim.cardIndex]) {
                const card = playerCards[claim.cardIndex];
                const calledNumbers = game.calledNumbers || [];
                
                const result = verifyBingo(card, calledNumbers, game.settings?.gameType);
                
                if (result.valid) {
                    validWinners.push({
                        ...claim,
                        ...result
                    });
                }
            }
        }
    });
    
    // Process winners if any and no winners yet
    if (validWinners.length > 0 && !game.winners) {
        processWinners(validWinners, game);
    }
    
    displayBingoClaims(claims, validWinners);
}

// Verify bingo claim
function verifyBingo(card, calledNumbers, gameType) {
    // Check based on game type
    switch(gameType) {
        case 'fullhouse':
            return verifyFullHouse(card, calledNumbers);
        case 'row':
            return verifyAnyRow(card, calledNumbers);
        case 'column':
            return verifyAnyColumn(card, calledNumbers);
        case 'diagonal':
            return verifyAnyDiagonal(card, calledNumbers);
        case 'fourcorners':
            return verifyFourCorners(card, calledNumbers);
        case 'random':
            return { valid: Math.random() > 0.5, type: 'random' };
        default:
            return verifyFullHouse(card, calledNumbers);
    }
}

// Verify full house
function verifyFullHouse(card, calledNumbers) {
    for (let row of card) {
        for (let num of row) {
            if (num !== 'FREE' && !calledNumbers.includes(num)) {
                return { valid: false };
            }
        }
    }
    return { valid: true, type: 'fullhouse' };
}

// Verify any row
function verifyAnyRow(card, calledNumbers) {
    for (let row of card) {
        let rowComplete = true;
        for (let num of row) {
            if (num !== 'FREE' && !calledNumbers.includes(num)) {
                rowComplete = false;
                break;
            }
        }
        if (rowComplete) {
            return { valid: true, type: 'row' };
        }
    }
    return { valid: false };
}

// Verify any column
function verifyAnyColumn(card, calledNumbers) {
    for (let col = 0; col < 5; col++) {
        let colComplete = true;
        for (let row = 0; row < 5; row++) {
            const num = card[row][col];
            if (num !== 'FREE' && !calledNumbers.includes(num)) {
                colComplete = false;
                break;
            }
        }
        if (colComplete) {
            return { valid: true, type: 'column' };
        }
    }
    return { valid: false };
}

// Verify any diagonal
function verifyAnyDiagonal(card, calledNumbers) {
    // Main diagonal
    let diag1Complete = true;
    for (let i = 0; i < 5; i++) {
        const num = card[i][i];
        if (num !== 'FREE' && !calledNumbers.includes(num)) {
            diag1Complete = false;
            break;
        }
    }
    if (diag1Complete) return { valid: true, type: 'diagonal' };
    
    // Other diagonal
    let diag2Complete = true;
    for (let i = 0; i < 5; i++) {
        const num = card[i][4 - i];
        if (num !== 'FREE' && !calledNumbers.includes(num)) {
            diag2Complete = false;
            break;
        }
    }
    if (diag2Complete) return { valid: true, type: 'diagonal' };
    
    return { valid: false };
}

// Verify four corners
function verifyFourCorners(card, calledNumbers) {
    const corners = [
        card[0][0],
        card[0][4],
        card[4][0],
        card[4][4]
    ];
    
    for (let corner of corners) {
        if (corner !== 'FREE' && !calledNumbers.includes(corner)) {
            return { valid: false };
        }
    }
    
    return { valid: true, type: 'fourcorners' };
}

// Process winners
function processWinners(winners, game) {
    const prizePerWinner = game.settings.prizeAmount / winners.length;
    
    const updates = {};
    
    // Add winners
    updates['activeGame/winners'] = winners.map(w => ({
        playerId: w.playerId,
        cardIndex: w.cardIndex,
        type: w.type,
        prize: prizePerWinner,
        verifiedAt: Date.now(),
        claimId: w.id
    }));
    
    // Add winning cards for display
    updates['activeGame/winningCards'] = winners.map(w => ({
        playerId: w.playerId,
        cardIndex: w.cardIndex,
        card: game.players[w.playerId].cards[w.cardIndex],
        type: w.type
    }));
    
    // Update game status
    updates['activeGame/status'] = 'completed';
    updates['activeGame/endedAt'] = Date.now();
    
    update(ref(database), updates)
        .then(() => {
            console.log('Winners processed successfully:', winners);
            
            // Show notification
            showNotification(`${winners.length} አሸናፊ(ዎች) ተገኝተዋል!`, 'success');
        })
        .catch(error => {
            console.error('Error processing winners:', error);
        });
}

// Display bingo claims
function displayBingoClaims(claims, validWinners) {
    const container = document.getElementById('bingoClaims');
    if (!container) return;
    
    if (claims.length === 0) {
        container.innerHTML = '<p class="no-data">ምንም የቢንጎ ጥያቄ የለም</p>';
        return;
    }
    
    let html = '<h3>🎯 የቢንጎ ጥያቄዎች</h3>';
    html += '<table class="claims-table">';
    html += '<tr><th>ተጫዋች</th><th>ካርድ</th><th>ሰዓት</th><th>አይነት</th><th>ሁኔታ</th><th>ድርጊት</th></tr>';
    
    claims.sort((a, b) => b.timestamp - a.timestamp).forEach(claim => {
        const isValid = validWinners.some(w => 
            w.playerId === claim.playerId && w.cardIndex === claim.cardIndex
        );
        
        const time = new Date(claim.timestamp).toLocaleTimeString();
        const isWinner = isValid && currentGame?.winners;
        
        html += `
            <tr class="${isWinner ? 'winner-row' : ''}">
                <td>${claim.playerId.substring(0, 8)}...</td>
                <td>ካርድ ${claim.cardIndex + 1}</td>
                <td>${time}</td>
                <td>${claim.type || '?'}</td>
                <td class="${isValid ? 'valid' : 'invalid'}">
                    ${isValid ? '✅ ትክክል' : '❌ ስህተት'}
                </td>
                <td>
                    ${!isWinner ? `<button onclick="viewClaimDetails('${claim.id}')" class="btn-small">ዝርዝር</button>` : '🏆 አሸናፊ'}
                </td>
            </tr>
        `;
    });
    
    html += '</table>';
    
    if (validWinners.length > 0 && !currentGame?.winners) {
        html += `<div class="action-buttons">
            <button onclick="confirmWinners()" class="btn btn-success">አሸናፊዎችን አረጋግጥ</button>
        </div>`;
    }
    
    container.innerHTML = html;
}

// View claim details
window.viewClaimDetails = function(claimId) {
    if (!currentGame || !currentGame.bingoClaims[claimId]) return;
    
    const claim = currentGame.bingoClaims[claimId];
    const player = currentGame.players[claim.playerId];
    
    if (!player) return;
    
    const card = player.cards[claim.cardIndex];
    const calledNumbers = currentGame.calledNumbers || [];
    
    let modalHtml = '<div class="claim-details-modal">';
    modalHtml += `<h2>የቢንጎ ጥያቄ ዝርዝር</h2>`;
    modalHtml += `<p><strong>ተጫዋች:</strong> ${claim.playerId}</p>`;
    modalHtml += `<p><strong>ካርድ ቁጥር:</strong> ${claim.cardIndex + 1}</p>`;
    modalHtml += `<p><strong>የጠየቀበት ሰዓት:</strong> ${new Date(claim.timestamp).toLocaleString()}</p>`;
    modalHtml += `<p><strong>የተጠራ አይነት:</strong> ${claim.type}</p>`;
    
    modalHtml += '<h3>ካርድ</h3>';
    modalHtml += '<div class="mini-card">';
    card.forEach(row => {
        modalHtml += '<div class="mini-row">';
        row.forEach(num => {
            const isCalled = num === 'FREE' || calledNumbers.includes(num);
            const cellClass = isCalled ? 'mini-cell called' : 'mini-cell';
            const displayNum = num === 'FREE' ? 'F' : num;
            modalHtml += `<span class="${cellClass}">${displayNum}</span>`;
        });
        modalHtml += '</div>';
    });
    modalHtml += '</div>';
    
    modalHtml += '<button onclick="closeClaimDetails()" class="btn btn-primary">ዝጋ</button>';
    modalHtml += '</div>';
    
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'claimDetailsModal';
    modal.innerHTML = modalHtml;
    document.body.appendChild(modal);
}

// Close claim details
window.closeClaimDetails = function() {
    const modal = document.getElementById('claimDetailsModal');
    if (modal) {
        modal.remove();
    }
}

// Confirm winners
window.confirmWinners = function() {
    if (!currentGame || !currentGame.bingoClaims) return;
    
    const claims = Object.values(currentGame.bingoClaims);
    const validWinners = [];
    
    claims.forEach(claim => {
        if (currentGame.players[claim.playerId]) {
            const card = currentGame.players[claim.playerId].cards[claim.cardIndex];
            const calledNumbers = currentGame.calledNumbers || [];
            const result = verifyBingo(card, calledNumbers, currentGame.settings?.gameType);
            
            if (result.valid) {
                validWinners.push({
                    ...claim,
                    ...result
                });
            }
        }
    });
    
    if (validWinners.length > 0) {
        processWinners(validWinners, currentGame);
    } else {
        alert('ምንም ትክክለኛ አሸናፊ አልተገኘም');
    }
}

// Manually call a number (admin)
export function adminCallNumber() {
    if (!currentGame) {
        alert('ንቁ ጨዋታ የለም');
        return;
    }
    
    if (currentGame.status !== 'active') {
        alert('ጨዋታው ንቁ አይደለም');
        return;
    }
    
    if (currentGame.winners) {
        alert('ጨዋታው አልቋል');
        return;
    }
    
    const newNumber = Math.floor(Math.random() * 75) + 1;
    
    if (!currentGame.calledNumbers || !currentGame.calledNumbers.includes(newNumber)) {
        const updates = {};
        const calledNumbers = currentGame.calledNumbers || [];
        calledNumbers.push(newNumber);
        
        updates['activeGame/calledNumbers'] = calledNumbers;
        updates['activeGame/lastCalledAt'] = Date.now();
        updates['activeGame/lastCalledBy'] = 'admin';
        
        update(ref(database), updates)
            .then(() => {
                console.log('Number called by admin:', newNumber);
                showNotification(`ቁጥር ${newNumber} ተጠርቷል`, 'info');
            })
            .catch(error => {
                console.error('Error calling number:', error);
                alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
            });
    } else {
        // Number already called, try again
        adminCallNumber();
    }
}

// Reset game completely
export function resetGame() {
    if (confirm('እርግጠኛ ነዎት ጨዋታውን ማጥፋት ይፈልጋሉ? ይህ ሁሉንም ውሂብ ይሰርዛል።')) {
        // Archive current game if exists
        if (currentGame) {
            archiveGame(currentGame);
        }
        
        set(ref(database, 'activeGame'), null)
            .then(() => {
                alert('ጨዋታ ተወግዷል');
            })
            .catch(error => {
                console.error('Error resetting game:', error);
                alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
            });
    }
}

// Get game statistics
export function getGameStats() {
    if (!currentGame) {
        alert('ንቁ ጨዋታ የለም');
        return;
    }
    
    const stats = {
        totalPlayers: currentGame.players ? Object.keys(currentGame.players).length : 0,
        totalCards: 0,
        totalCalledNumbers: currentGame.calledNumbers?.length || 0,
        gameDuration: currentGame.startTime ? Math.floor((Date.now() - currentGame.startTime) / 1000) : 0,
        gameType: currentGame.settings?.gameType || 'fullhouse',
        cardPrice: currentGame.settings?.cardPrice || 10,
        totalPrize: currentGame.settings?.prizeAmount || 20,
        totalBets: 0
    };
    
    // Calculate total cards and bets
    if (currentGame.players) {
        Object.values(currentGame.players).forEach(player => {
            stats.totalCards += player.cards.length;
            stats.totalBets += player.balance || 0;
        });
    }
    
    // Calculate potential profit
    const potentialProfit = stats.totalBets - stats.totalPrize;
    
    let statsMessage = '📊 የጨዋታ ስታቲስቲክስ:\n\n';
    statsMessage += `ተጫዋቾች: ${stats.totalPlayers}\n`;
    statsMessage += `ጠቅላላ ካርዶች: ${stats.totalCards}\n`;
    statsMessage += `የተጠሩ ቁጥሮች: ${stats.totalCalledNumbers}\n`;
    statsMessage += `ጠቅላላ ውርርድ: ${stats.totalBets} ብር\n`;
    statsMessage += `ሽልማት: ${stats.totalPrize} ብር\n`;
    statsMessage += `እምቅ ትርፍ: ${potentialProfit} ብር\n`;
    statsMessage += `የጨዋታ ሰዓት: ${Math.floor(stats.gameDuration / 60)} ደቂቃ ${stats.gameDuration % 60} ሰከንድ\n`;
    statsMessage += `የጨዋታ አይነት: ${getGameTypeName(stats.gameType)}\n`;
    statsMessage += `የካርድ ዋጋ: ${stats.cardPrice} ብር`;
    
    alert(statsMessage);
}

// Manual winner declaration
export function declareWinner(playerId, cardIndex) {
    if (!currentGame) {
        alert('ንቁ ጨዋታ የለም');
        return;
    }
    
    if (!currentGame.players[playerId]) {
        alert('ተጫዋች አልተገኘም');
        return;
    }
    
    if (!currentGame.players[playerId].cards[cardIndex]) {
        alert('ካርድ አልተገኘም');
        return;
    }
    
    const winner = {
        playerId: playerId,
        cardIndex: cardIndex,
        type: 'manual',
        timestamp: Date.now(),
        declaredBy: 'admin'
    };
    
    processWinners([winner], currentGame);
}

// Clear all bingo claims
export function clearBingoClaims() {
    if (!currentGame) {
        alert('ንቁ ጨዋታ የለም');
        return;
    }
    
    if (confirm('ሁሉንም የቢንጎ ጥያቄዎች መሰረዝ ይፈልጋሉ?')) {
        set(ref(database, 'activeGame/bingoClaims'), null)
            .then(() => {
                alert('የቢንጎ ጥያቄዎች ተሰርዘዋል');
            })
            .catch(error => {
                console.error('Error clearing claims:', error);
                alert('ስህተት ተከስቷል። እንደገና ይሞክሩ።');
            });
    }
}

// Export game data
export function exportGameData() {
    if (!currentGame) {
        alert('ምንም ውሂብ የለም');
        return;
    }
    
    const exportData = {
        game: currentGame,
        exportedAt: Date.now(),
        exportedBy: 'admin',
        stats: {
            totalPlayers: currentGame.players ? Object.keys(currentGame.players).length : 0,
            totalCalledNumbers: currentGame.calledNumbers?.length || 0,
            hasWinners: !!currentGame.winners
        }
    };
    
    const dataStr = JSON.stringify(exportData, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const exportFileDefaultName = `bingo-game-${new Date().toISOString().slice(0,19).replace(/:/g, '-')}.json`;
    
    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();
    
    alert('ውሂብ ተልኳል!');
}

// Initialize admin page
document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    if (path.includes('dashboard.html') || path.includes('admin')) {
        initAdminDashboard();
    }
});

// Add keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl + N: New game
    if (e.ctrlKey && e.key === 'n') {
        e.preventDefault();
        startNewGame();
    }
    
    // Ctrl + C: Call number
    if (e.ctrlKey && e.key === 'c') {
        e.preventDefault();
        adminCallNumber();
    }
    
    // Ctrl + E: End game
    if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        endGame();
    }
    
    // Ctrl + S: Save settings
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        saveSettings();
    }
});