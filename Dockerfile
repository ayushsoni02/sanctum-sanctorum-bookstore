FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency specifications first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Copy application and frontend code
COPY app/ ./app/
COPY frontend/ ./frontend/

# Expose standard port
EXPOSE 8000

ENV PORT=8000

# Run uvicorn bound to 0.0.0.0
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
