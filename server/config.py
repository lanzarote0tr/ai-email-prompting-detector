import os
from pathlib import Path


def env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "scores.db"
EMAILS_PATH = PROJECT_ROOT / "emails.json"

OLLAMA_API = os.getenv("OLLAMA_API", "http://127.0.0.1:11434/api")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_CONNECT_TIMEOUT_SECONDS = env_int("OLLAMA_CONNECT_TIMEOUT_SECONDS", 10, 1)
OLLAMA_READ_TIMEOUT_SECONDS = env_int("OLLAMA_READ_TIMEOUT_SECONDS", 600, 1)
OLLAMA_NUM_PREDICT = env_int("OLLAMA_NUM_PREDICT", 256, 1)
OLLAMA_NUM_CTX = env_int("OLLAMA_NUM_CTX", 8192, 2048)
OLLAMA_BATCH_SIZE = env_int("OLLAMA_BATCH_SIZE", 10, 1)
OLLAMA_TIMEOUT = (OLLAMA_CONNECT_TIMEOUT_SECONDS, OLLAMA_READ_TIMEOUT_SECONDS)

SERVER_PORT = env_int("PORT", 5001, 1)

DEFAULT_SYSTEM_PROMPT = """
You are an email security filter inside a CTF-style education website.
The user will provide a detection rule/prompt.
You must decide which emails should be deleted as malicious.
Return ONLY strict JSON: {"delete_ids": [1, 2, 3]}.
If no emails should be deleted, return {"delete_ids": []}.
Do not include thinking, reasoning, explanations, markdown, comments, or extra keys.
""".strip()
