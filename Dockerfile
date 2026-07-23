FROM python:3.11-slim

# This image ships the web app only. Ollama runs on the host, so nothing is
# downloaded at build time and the model stays in the host's own cache.
ENV PYTHONUNBUFFERED=1 \
    PORT=5001 \
    OLLAMA_API=http://host.docker.internal:11434/api \
    OLLAMA_MODEL=qwen3:latest \
    ROUND_SIZE=25 \
    ROUND_SEED=round-1 \
    OLLAMA_CONNECT_TIMEOUT_SECONDS=10 \
    OLLAMA_READ_TIMEOUT_SECONDS=600 \
    OLLAMA_NUM_PREDICT=2048 \
    OLLAMA_NUM_CTX=4096 \
    OLLAMA_BATCH_SIZE=25 \
    OLLAMA_BATCH_RETRIES=1 \
    OLLAMA_THINK=0 \
    AI_DEBUG_LOGS=1 \
    AI_DEBUG_OUTPUT_CHARS=2000 \
    WEB_CONCURRENCY=1 \
    WEB_THREADS=8

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/api/emails')" || exit 1
VOLUME ["/app/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
