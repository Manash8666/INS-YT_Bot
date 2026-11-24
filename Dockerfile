# ── Build ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir build && \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] python-multipart \
        pydantic pydantic-settings python-dotenv \
        google-api-python-client google-auth-httplib2 google-auth-oauthlib \
        httpx SQLAlchemy alembic cryptography passlib python-jose \
        structlog Pillow anyio

# ── Runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY src/  ./src/
COPY api_server.py main.py ./

# Create non-root user
RUN addgroup --system botgroup && adduser --system --ingroup botgroup botuser && \
    mkdir -p /app/data && chown -R botuser:botgroup /app
USER botuser

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info", "--access-log"]
