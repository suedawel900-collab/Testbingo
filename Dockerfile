```dockerfile
FROM node:18-alpine

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy app source
COPY . .

# Expose port
EXPOSE 3000

# Set environment variables
ENV NODE_ENV=production
ENV DB_PATH=./data/bingo.db

# Start bot
CMD [ "node", "index.js" ]