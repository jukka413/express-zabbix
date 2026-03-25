# ---------------------------------------------------------------------------
# Stage 1: dependency builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY requirements.txt .

RUN uv pip install --system --no-cache -r requirements.txt


# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY --chown=app:app main.py .

USER app

# Default fallback — overridden by env_file / environment in docker-compose
ENV PORT=8081

# EXPOSE is documentation-only; real port comes from docker-compose at runtime
EXPOSE ${PORT}

# Shell form so $PORT is expanded from the runtime environment
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ['PORT'] + '/status')"

CMD ["python", "main.py"]
