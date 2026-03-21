# ---------------------------------------------------------------------------
# Stage 1: builder — install Python deps into a clean venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir uv

# Copy only dependency manifests first (cache layer)
COPY pyproject.toml ./
COPY src/ ./src/

# Create a venv and install all dependencies
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -e ".[dev]"

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# git is required for incremental indexing (git diff --name-only)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY src/ /app/src/

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Runtime environment (overridden via docker-compose / -e flags)
ENV WORKSPACE_ROOT=/workspace
ENV INDEX_DB_PATH=/data/onec-hbk-bsl_index.sqlite
ENV MCP_PORT=8051
ENV LOG_LEVEL=info

WORKDIR /app

# Data directory for SQLite index
VOLUME ["/data", "/workspace"]

EXPOSE 8051

# Health check — MCP server exposes /health on the HTTP port
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${MCP_PORT:-8051}/health')" || exit 1

CMD ["onec-hbk-bsl", "--mcp"]
