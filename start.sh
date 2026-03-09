#!/bin/bash
# start.sh - Run both web and bot processes

echo "========================================="
echo "Starting MK BINGO - Web + Bot"
echo "========================================="
echo "Web server will run on port $PORT"
echo "Bot will run in background"

# Start the bot in the background
python bot.py &
BOT_PID=$!
echo "✅ Bot started with PID: $BOT_PID"

# Start the web server
echo "✅ Starting web server..."
gunicorn app:application --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 2 --timeout 120

# If web server stops, kill the bot
echo "Stopping bot process..."
kill $BOT_PID 2>/dev/null