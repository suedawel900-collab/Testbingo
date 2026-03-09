FROM node:18-alpine

# Create app directory
WORKDIR /usr/src/app

# Install SQLite (useful for debugging)
RUN apk add --no-cache sqlite

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy app source
COPY . .

# Create directory for database (Railway will mount volume here)
# This ensures the directory exists before the app starts
RUN mkdir -p /app/data && \
    chown -R node:node /app/data && \
    chown -R node:node /usr/src/app

# Switch to non-root user for security
USER node

# Expose port for web interface
EXPOSE 3000

# Set environment variables
ENV NODE_ENV=production
ENV PORT=3000
ENV DB_PATH=/app/data/bingo.db

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})" || exit 1

# Start the bot
CMD [ "node", "index.js" ]