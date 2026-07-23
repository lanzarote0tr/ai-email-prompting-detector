#!/usr/bin/env sh
set -eu

: "${PORT:=5001}"
: "${OLLAMA_API:=http://host.docker.internal:11434/api}"
: "${OLLAMA_MODEL:=qwen3:4b}"
: "${WEB_CONCURRENCY:=1}"
: "${WEB_THREADS:=8}"

# There is no Ollama in this image. Probe the host's one now so a wrong OLLAMA_API
# or a missing model is reported at startup instead of halfway through a run.
# Warn only: the app is still useful for browsing emails while Ollama comes up.
python - <<'PY' || true
import json
import os
import urllib.error
import urllib.request

api = os.environ["OLLAMA_API"].rstrip("/")
model = os.environ["OLLAMA_MODEL"]
try:
    with urllib.request.urlopen(f"{api}/tags", timeout=5) as resp:
        tags = json.load(resp)
except (urllib.error.URLError, OSError, ValueError) as e:
    print(f"WARNING: cannot reach Ollama at {api} ({e}).")
    print("         Start it on the host with: OLLAMA_HOST=0.0.0.0 ollama serve")
    print("         On Linux also run the container with --add-host=host.docker.internal:host-gateway")
else:
    names = [m.get("name", "") for m in tags.get("models", [])]
    if model in names:
        print(f"Ollama OK at {api}, using model {model}")
    else:
        print(f"WARNING: Ollama at {api} has no model named {model}.")
        print(f"         Pull it on the host with: ollama pull {model}")
        print(f"         Available: {', '.join(names) or 'none'}")
PY

exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --threads "${WEB_THREADS}" \
  --access-logfile - \
  --access-logformat '%(h)s %(r)s %(s)s %(b)s %(D)sµs' \
  --timeout 0 \
  server.app:app
