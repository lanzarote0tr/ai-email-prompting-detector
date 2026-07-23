import os
from pathlib import Path


def env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "scores.db"
EMAILS_PATH = PROJECT_ROOT / "emails.json"

OLLAMA_API = os.getenv("OLLAMA_API", "http://127.0.0.1:11434/api")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:latest")
OLLAMA_CONNECT_TIMEOUT_SECONDS = env_int("OLLAMA_CONNECT_TIMEOUT_SECONDS", 10, 1)
OLLAMA_READ_TIMEOUT_SECONDS = env_int("OLLAMA_READ_TIMEOUT_SECONDS", 600, 1)
OLLAMA_NUM_PREDICT = env_int("OLLAMA_NUM_PREDICT", 2048, 1)
# A 25-email batch is ~2700 prompt tokens; 4096 leaves headroom without making
# Ollama reserve KV cache the run never uses.
OLLAMA_NUM_CTX = env_int("OLLAMA_NUM_CTX", 4096, 2048)
OLLAMA_BATCH_SIZE = env_int("OLLAMA_BATCH_SIZE", 25, 1)
OLLAMA_BATCH_RETRIES = env_int("OLLAMA_BATCH_RETRIES", 1, 0)
OLLAMA_THINK = env_bool("OLLAMA_THINK", False)
OLLAMA_TIMEOUT = (OLLAMA_CONNECT_TIMEOUT_SECONDS, OLLAMA_READ_TIMEOUT_SECONDS)
AI_DEBUG_LOGS = env_bool("AI_DEBUG_LOGS", True)
AI_DEBUG_OUTPUT_CHARS = env_int("AI_DEBUG_OUTPUT_CHARS", 2000, 1)

# How many emails one attempt is graded on, drawn from the emails.json pool.
# Run time scales with this almost linearly: the model has to read every email,
# and reading the prompt is ~90% of the work. 25 measured 13.1s on qwen3:latest,
# 35 measured 18.6s, so 25 is what fits a 15s budget. 0 means the whole pool.
ROUND_SIZE = env_int("ROUND_SIZE", 25, 0)
ROUND_SEED = os.getenv("ROUND_SEED", "round-1")

SERVER_PORT = env_int("PORT", 5001, 1)
# Off by default: the app binds 0.0.0.0, and Werkzeug's debugger is a remote shell.
SERVER_DEBUG = env_bool("FLASK_DEBUG", False)

DEFAULT_SYSTEM_PROMPT = """
You are an email security filter inside a CTF-style education website.
The user will provide a detection rule/prompt.
You must decide which emails should be deleted as malicious.
Return ONLY strict JSON: {"delete_ids": [1, 2, 3]}.
If no emails should be deleted, return {"delete_ids": []}.
Do not include thinking, reasoning, explanations, markdown, comments, or extra keys.
""".strip()
