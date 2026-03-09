```dockerfile
FROM node:18-alpine

# Create app directory
WORKDIR /usr/src/app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy app source
COPY . .

# Create volume for database
VOLUME [ "/usr/src/app/data" ]

# Expose port
EXPOSE 3000

# Set environment variables
ENV NODE_ENV=production
ENV DB_PATH=./data/bingo.db

# Start bot
CMD [ "node", "index.js" ]