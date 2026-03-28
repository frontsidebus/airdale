# MERLIN Orchestrator + Web Server - Multi-stage Dockerfile
# Builds the Python orchestration layer and web UI server.
# Build context must be the project root (not ./orchestrator).

# =============================================================================
# Stage 1: Build - install Python dependencies
# =============================================================================
FROM python:3.12-slim AS build

WORKDIR /build

# Install build-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and source (hatchling needs the package to build)
COPY orchestrator/pyproject.toml ./orchestrator/
COPY orchestrator/orchestrator/ ./orchestrator/orchestrator/

# Install dependencies into a virtual environment so we can copy them cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ./orchestrator

# Install web server dependencies
COPY web/requirements.txt ./web/
RUN pip install --no-cache-dir -r ./web/requirements.txt

# =============================================================================
# Stage 2: Runtime - slim image with only what we need
# =============================================================================
FROM python:3.12-slim AS runtime

# System dependencies for audio processing and general operation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libportaudio2 \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the build stage
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd --gid 1000 merlin \
    && useradd --uid 1000 --gid merlin --create-home merlin

WORKDIR /app

# Copy application source
COPY orchestrator/orchestrator/ ./orchestrator/orchestrator/
COPY orchestrator/pyproject.toml ./orchestrator/
COPY web/ ./web/
COPY data/ ./data/

# Ensure the app directory is owned by our non-root user
RUN chown -R merlin:merlin /app

USER merlin

EXPOSE 3838

# Run the web server (serves both UI and API)
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "3838"]
