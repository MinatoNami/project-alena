# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# Runtime stage
FROM node:22-alpine

WORKDIR /app

COPY --from=builder /app/.output ./.output
COPY package.json package-lock.json ./

# Install only production dependencies
RUN npm ci --omit=dev

ENV NODE_ENV=production \
    NUXT_HOST=localhost \
    NUXT_PORT=3000 \
    NUXT_PUBLIC_LLM_API_URL=http://localhost:8001 \
    NUXT_PUBLIC_OLLAMA_URL=http://localhost:11434 \
    NUXT_PUBLIC_WS_AUDIO_URL=ws://localhost:8001

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
