# Single-container deployment image: React static bundle + FastAPI service.
FROM node:22-alpine AS frontend-build
WORKDIR /workspace
COPY package.json ./package.json
COPY package-lock.json ./package-lock.json
COPY frontend/package.json ./frontend/package.json
RUN npm ci --no-audit --no-fund
COPY frontend ./frontend
RUN npm run build --workspace frontend

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    DATA_DIR=/app/data \
    CACHE_TTL_SECONDS=900 \
    ALLOW_DEMO_FALLBACK=true
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend-build /workspace/frontend/dist ./static
RUN mkdir -p /app/data && useradd --create-home --uid 10001 winddesk && chown -R winddesk:winddesk /app
USER winddesk
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
