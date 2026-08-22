# syntax=docker/dockerfile:1

FROM python:3.11-slim AS backend-builder

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN useradd --create-home --uid 10001 appuser
COPY --from=backend-builder /install /usr/local
COPY --chown=appuser:appuser src ./src
RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/live')" || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:22-alpine AS frontend-deps

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS frontend-builder

WORKDIR /app
COPY --from=frontend-deps /app/node_modules ./node_modules
COPY frontend/ ./
ARG NEXT_PUBLIC_API_URL=/backend
ARG BACKEND_URL=http://backend:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    BACKEND_URL=${BACKEND_URL}
RUN npm run build

FROM node:22-alpine AS frontend

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

COPY --from=frontend-builder --chown=node:node /app/package.json /app/package-lock.json ./
COPY --from=frontend-builder --chown=node:node /app/node_modules ./node_modules
COPY --from=frontend-builder --chown=node:node /app/.next ./.next
COPY --from=frontend-builder --chown=node:node /app/public ./public
COPY --from=frontend-builder --chown=node:node /app/next.config.ts ./next.config.ts

USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0"]
