# Kokoro TTS server for MERLIN local inference
#
# Build:   docker build -t merlin-tts .
# Run:     docker run --gpus all -p 9091:9091 -v ./models/tts:/models merlin-tts

FROM python:3.11-slim

# System dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PyTorch with CUDA support (Kokoro requires it for GPU inference)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu121

COPY server.py .

EXPOSE 9091

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=60s \
    CMD curl -f http://localhost:9091/health || exit 1

CMD ["python", "server.py"]
