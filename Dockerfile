FROM ollama/ollama:latest

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PORT=5001 \
    OLLAMA_API=http://127.0.0.1:11434/api \
    OLLAMA_MODEL=qwen3:4b \
    OLLAMA_CONNECT_TIMEOUT_SECONDS=10 \
    OLLAMA_READ_TIMEOUT_SECONDS=600 \
    OLLAMA_NUM_PREDICT=256 \
    OLLAMA_NUM_CTX=8192 \
    OLLAMA_BATCH_SIZE=10 \
    WEB_CONCURRENCY=1 \
    WEB_THREADS=8

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/api/emails >/dev/null || exit 1
VOLUME ["/root/.ollama", "/app/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
