# Stage 1: build wheels for all runtime dependencies
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# Stage 2: slim runtime image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:///./ArchLens.db

WORKDIR /app

# Install dependencies as root, then drop privileges
COPY --from=builder /build/wheels /wheels
RUN pip install /wheels/* && rm -rf /wheels \
    && useradd --create-home --uid 1000 appuser \
    && chown appuser:appuser /app

COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000

# Health check (python is used because slim images have no curl)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)"

# Apply database migrations, then start the app (PORT is set by hosts such as Render)
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
