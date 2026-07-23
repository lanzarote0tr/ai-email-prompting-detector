#!/usr/bin/env sh
set -eu

: "${PORT:=5001}"
: "${OLLAMA_API:=http://127.0.0.1:11434/api}"
: "${OLLAMA_MODEL:=qwen3:0.6b}"
: "${WEB_CONCURRENCY:=1}"
: "${WEB_THREADS:=8}"

ollama serve &
OLLAMA_PID="$!"
WEB_PID=""

cleanup() {
  kill "$OLLAMA_PID" 2>/dev/null || true
  if [ -n "$WEB_PID" ]; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

until curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; do
  sleep 1
done

if ! ollama list | awk 'NR > 1 {print $1}' | grep -qx "$OLLAMA_MODEL"; then
  ollama pull "$OLLAMA_MODEL"
fi

gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --threads "${WEB_THREADS}" \
  --timeout 0 \
  app:app &
WEB_PID="$!"

wait "$WEB_PID"
