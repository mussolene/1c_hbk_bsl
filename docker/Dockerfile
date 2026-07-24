# ---------------------------------------------------------------------------
# Stage 1: builder — install Python deps into a clean venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only dependency manifests first (cache layer)
COPY pyproject.toml ./
COPY src/ ./src/

# Create a venv with the MCP runtime dependency set.
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir ".[mcp]"

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

ENV PATH="/opt/venv/bin:$PATH"
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

# Check that the MCP HTTP listener accepts connections.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os,socket; socket.create_connection(('127.0.0.1', int(os.environ.get('MCP_PORT', '8051'))), 5).close()" || exit 1

CMD ["onec-hbk-bsl", "mcp"]
