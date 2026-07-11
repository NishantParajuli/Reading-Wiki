# --- Stage 0: Build the frontend bundle ---
FROM node:20-slim AS frontend
WORKDIR /fe
COPY novelwiki/frontend/package.json novelwiki/frontend/package-lock.json ./
RUN npm ci
COPY novelwiki/frontend/ ./
RUN npm run build

# --- Stage 1: Build the virtual environment ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Optimize Python/uv build environment
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy configuration files to prepare for dependency installation
COPY pyproject.toml uv.lock ./

# Install dependencies (without installing the project package itself)
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application source code
COPY . .

# Perform a full sync to ensure the project package is installed
RUN uv sync --frozen --no-dev

# --- Stage 2: Runtime image ---
FROM python:3.12-slim-bookworm

# Create a dedicated non-root group and user
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --shell /bin/bash --create-home app

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Copy the application source code, config, and entrypoints
COPY --from=builder --chown=app:app /app/novelwiki /app/novelwiki
COPY --from=builder --chown=app:app /app/main.py /app/main.py
COPY --from=builder --chown=app:app /app/pyproject.toml /app/pyproject.toml

# The compiled SPA replaces whatever source tree was copied above
COPY --from=frontend --chown=app:app /fe/dist /app/novelwiki/frontend/dist

# Create the data directory for BM25 indexes and scraped data
RUN mkdir -p /app/data && chown -R app:app /app/data

# Place the virtualenv binaries at the beginning of PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# Run as non-root user
USER app

# Set default host and port environment variables for uvicorn
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=8001

# Expose the default port
EXPOSE 8001

# Start the application server
CMD ["uvicorn", "novelwiki.api.app:app"]
