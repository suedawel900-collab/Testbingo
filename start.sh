#!/bin/bash
# start.sh - Start both web and bot processes

echo "Starting MK BINGO..."

# Start the bot in the background
python bot.py &
BOT_PID=$!
echo "Bot started with PID: $BOT_PID"

# Start the web server
echo "Starting web server..."
gunicorn app:application --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 2 --timeout 120

# When web server stops, kill the bot
kill $BOT_PID