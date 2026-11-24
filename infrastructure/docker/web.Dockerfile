# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- Development image: hot reload with the source bind-mounted ---
FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/ ./
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

# --- Production build ---
FROM deps AS build
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* values are compiled into the browser bundle at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY apps/web/ ./
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S pare && adduser -S pare -G pare
COPY --from=build --chown=pare:pare /app/.next/standalone ./
COPY --from=build --chown=pare:pare /app/.next/static ./.next/static
USER pare
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "server.js"]
