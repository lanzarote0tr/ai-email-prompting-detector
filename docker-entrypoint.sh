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

model = os.environ["OLLAMA_MODEL"]
apis = [a.strip().rstrip("/") for a in os.environ["OLLAMA_API"].split(",") if a.strip()]
usable = 0
for api in apis:
    try:
        with urllib.request.urlopen(f"{api}/tags", timeout=5) as resp:
            tags = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"WARNING: cannot reach Ollama at {api} ({e}).")
        print("         Start it on that machine with: OLLAMA_HOST=0.0.0.0 ollama serve")
        print("         On Linux also run the container with --add-host=host.docker.internal:host-gateway")
        continue
    names = [m.get("name", "") for m in tags.get("models", [])]
    if model in names:
        usable += 1
        print(f"Ollama OK at {api}, using model {model}")
    else:
        print(f"WARNING: Ollama at {api} has no model named {model}.")
        print(f"         Pull it there with: ollama pull {model}")
        print(f"         Available: {', '.join(names) or 'none'}")

if len(apis) > 1:
    print(f"{usable}/{len(apis)} hosts ready; batches are spread across them.")
if not usable:
    print("WARNING: no usable Ollama host. Browsing works, but running the filter will fail.")
PY

exec gunicorn \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --threads "${WEB_THREADS}" \
  --access-logfile - \
  --access-logformat '%(h)s %(r)s %(s)s %(b)s %(D)sµs' \
  --timeout 0 \
  server.app:app
