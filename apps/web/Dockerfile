FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=
ARG NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=
ENV API_URL=${API_URL}
ENV NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=${NEXT_PUBLIC_GOOGLE_MAPS_API_KEY}
ENV NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=${NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=8080
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 8080
CMD ["node", "server.js"]
