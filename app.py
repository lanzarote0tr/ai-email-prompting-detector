import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

OLLAMA_API = os.getenv("OLLAMA_API", "http://127.0.0.1:11434/api")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:0.6b")
try:
    OLLAMA_CONNECT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_CONNECT_TIMEOUT_SECONDS", "10"))
except ValueError:
    OLLAMA_CONNECT_TIMEOUT_SECONDS = 10
try:
    OLLAMA_READ_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_READ_TIMEOUT_SECONDS", "600"))
except ValueError:
    OLLAMA_READ_TIMEOUT_SECONDS = 600
try:
    OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
except ValueError:
    OLLAMA_NUM_PREDICT = 512
OLLAMA_CONNECT_TIMEOUT_SECONDS = max(1, OLLAMA_CONNECT_TIMEOUT_SECONDS)
OLLAMA_READ_TIMEOUT_SECONDS = max(1, OLLAMA_READ_TIMEOUT_SECONDS)
OLLAMA_NUM_PREDICT = max(1, OLLAMA_NUM_PREDICT)
OLLAMA_TIMEOUT = (OLLAMA_CONNECT_TIMEOUT_SECONDS, OLLAMA_READ_TIMEOUT_SECONDS)
OLLAMA_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "delete_ids": {
            "type": "array",
            "items": {"type": "integer"},
        },
    },
    "required": ["delete_ids"],
    "additionalProperties": False,
}
try:
    SERVER_PORT = int(os.getenv("PORT", "5001"))
except ValueError:
    SERVER_PORT = 5001
DEFAULT_SYSTEM_PROMPT = """
You are an email security filter inside a CTF-style education website.
The user will provide a detection rule/prompt.
You must decide which emails should be deleted as malicious.
Return ONLY strict JSON: {"delete_ids": [1, 2, 3]}.
Do not include thinking, reasoning, explanations, markdown, comments, or extra keys.
""".strip()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "scores.db"
EMAILS_PATH = BASE_DIR / "emails.json"

app = Flask(__name__)
sock = Sock(app)


class AiFilterError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL,
                score INTEGER NOT NULL,
                tp INTEGER NOT NULL,
                fp INTEGER NOT NULL,
                fn INTEGER NOT NULL,
                tn INTEGER NOT NULL,
                deleted_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(scores)").fetchall()}
        if "system_prompt" not in columns:
            con.execute("ALTER TABLE scores ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''")
        con.commit()


def load_emails() -> list[dict[str, Any]]:
    """Load the exercise dataset from emails.json.

    The UI and scorer expect each item to contain the required fields below.
    Invalid datasets fail fast instead of silently replacing the exercise data.
    """
    required_fields = {
        "id",
        "sender",
        "subject",
        "body",
        "date",
        "attachment",
        "is_malicious",
        "indicators",
    }

    with EMAILS_PATH.open(encoding="utf-8") as f:
        emails = json.load(f)
    if not isinstance(emails, list):
        raise ValueError("emails.json must contain a list")

    normalized = []
    seen_ids = set()
    for i, email in enumerate(emails, start=1):
        if not isinstance(email, dict):
            raise ValueError(f"email #{i} must be an object")
        missing = required_fields - email.keys()
        if missing:
            raise ValueError(f"email #{i} is missing fields: {sorted(missing)}")

        item = dict(email)
        item["id"] = int(item["id"])
        if item["id"] <= 0:
            raise ValueError(f"email #{i} id must be positive")
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate email id: {item['id']}")
        seen_ids.add(item["id"])
        item["sender"] = str(item["sender"])
        item["subject"] = str(item["subject"])
        item["body"] = str(item["body"])
        item["date"] = str(item["date"])
        item["attachment"] = str(item.get("attachment") or "")
        if not isinstance(item["is_malicious"], bool):
            raise ValueError(f"email #{i} is_malicious must be a boolean")
        if not isinstance(item["indicators"], list):
            raise ValueError(f"email #{i} indicators must be a list")
        item["indicators"] = [str(x) for x in item["indicators"]]
        if not isinstance(item.get("read", False), bool):
            raise ValueError(f"email #{i} read must be a boolean")
        if not isinstance(item.get("deleted", False), bool):
            raise ValueError(f"email #{i} deleted must be a boolean")
        item["read"] = item.get("read", False)
        item["deleted"] = item.get("deleted", False)
        normalized.append(item)

    return sorted(normalized, key=lambda e: e["id"])


EMAILS = load_emails()


def compact_email_for_ai(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": email["id"],
        "sender": email["sender"],
        "subject": email["subject"],
        "body": email["body"],
        "attachment": email["attachment"],
    }


def ollama_endpoint() -> str:
    endpoint = OLLAMA_API.rstrip("/")
    if not endpoint.endswith("/generate"):
        endpoint += "/generate"
    return endpoint


def ollama_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def build_ollama_payload(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
    return {
        "model": OLLAMA_MODEL,
        "stream": stream,
        "format": OLLAMA_OUTPUT_SCHEMA,
        "system": system_prompt,
        "options": {
            "temperature": 0,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
        "prompt": (
            "/no_think\n\n"
            "User detection prompt:\n"
            + user_prompt
            + "\n\nEmails JSON:\n"
            + json.dumps([compact_email_for_ai(e) for e in emails], ensure_ascii=False)
            + '\n\nReturn only this JSON object shape: {"delete_ids":[1,2,3]}.'
        ),
    }


def strip_markdown_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def remove_thinking_blocks(content: str) -> str:
    cleaned = content
    while True:
        start = cleaned.lower().find("<think>")
        if start == -1:
            return cleaned.strip()
        end = cleaned.lower().find("</think>", start)
        if end == -1:
            return cleaned[:start].strip()
        cleaned = cleaned[:start] + cleaned[end + len("</think>"):]


def extract_first_json_object(content: str) -> str | None:
    start = content.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(content)):
        char = content[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:idx + 1]

    return None


def normalize_ai_json_text(content: str) -> str:
    cleaned = strip_markdown_json_fence(remove_thinking_blocks(content))
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        extracted = extract_first_json_object(cleaned)
        if extracted is not None:
            return extracted
        return cleaned


def parse_ai_delete_ids(content: str, emails: list[dict[str, Any]]) -> list[int]:
    if not isinstance(content, str):
        raise AiFilterError("AI API response did not contain a text response.")
    normalized = normalize_ai_json_text(content)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as e:
        snippet = content.strip().replace("\n", " ")[:300]
        raise AiFilterError(
            'AI output must be valid JSON like {"delete_ids": [1, 2, 3]}. '
            f"Raw output starts with: {snippet!r}"
        ) from e
    if not isinstance(parsed, dict) or not isinstance(parsed.get("delete_ids"), list):
        raise AiFilterError('AI output must be a JSON object with a "delete_ids" list.')

    email_ids = {e["id"] for e in emails}
    delete_ids = []
    invalid_ids = []
    for raw_id in parsed["delete_ids"]:
        try:
            email_id = int(raw_id)
        except (TypeError, ValueError):
            raise AiFilterError(f"AI returned a non-integer email id: {raw_id!r}")
        if email_id not in email_ids:
            invalid_ids.append(email_id)
        else:
            delete_ids.append(email_id)

    if invalid_ids:
        raise AiFilterError(f"AI returned unknown email ids: {sorted(set(invalid_ids))}")

    return sorted(set(delete_ids))


def call_ollama(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]]) -> tuple[list[int], str]:
    endpoint = ollama_endpoint()

    try:
        resp = requests.post(
            endpoint,
            headers=ollama_headers(),
            json=build_ollama_payload(system_prompt, user_prompt, emails, stream=False),
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("top-level response must be a JSON object")
    except requests.Timeout as e:
        raise AiFilterError(
            f"AI request timed out. Connect timeout: {OLLAMA_CONNECT_TIMEOUT_SECONDS}s, "
            f"read timeout: {OLLAMA_READ_TIMEOUT_SECONDS}s.",
            504,
        ) from e
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        raise AiFilterError(f"Ollama returned HTTP {status}. Check OLLAMA_API and OLLAMA_MODEL.") from e
    except requests.RequestException as e:
        raise AiFilterError(
            f"Could not reach local Ollama at {endpoint}. Start Ollama and pull the configured model ({OLLAMA_MODEL})."
        ) from e
    except ValueError as e:
        raise AiFilterError(f"AI API returned invalid JSON response: {e}") from e

    content = data.get("response") or data.get("message", {}).get("content")
    return parse_ai_delete_ids(content, emails), "local-ollama"


def call_ollama_streaming(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]], progress) -> tuple[list[int], str]:
    endpoint = ollama_endpoint()
    progress("connecting", f"Connecting to local Ollama at {endpoint}")
    progress(
        "waiting",
        f"Waiting for {OLLAMA_MODEL}. First run/model load can take several minutes; read timeout is {OLLAMA_READ_TIMEOUT_SECONDS}s.",
    )

    try:
        with requests.post(
            endpoint,
            headers=ollama_headers(),
            json=build_ollama_payload(system_prompt, user_prompt, emails, stream=True),
            timeout=OLLAMA_TIMEOUT,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            progress("generating", f"Ollama is analyzing {len(emails)} emails with {OLLAMA_MODEL}")

            chunks = []
            chunk_count = 0
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as e:
                    raise AiFilterError(f"Ollama stream returned invalid JSON: {e}") from e
                if not isinstance(event, dict):
                    raise AiFilterError("Ollama stream returned a non-object event.")
                token = event.get("response")
                if isinstance(token, str):
                    chunks.append(token)
                    chunk_count += 1
                    progress("generating", f"Received {chunk_count} response chunks")
                if event.get("done"):
                    break
    except requests.Timeout as e:
        raise AiFilterError(
            f"AI request timed out. Connect timeout: {OLLAMA_CONNECT_TIMEOUT_SECONDS}s, "
            f"read timeout: {OLLAMA_READ_TIMEOUT_SECONDS}s. "
            f"Use a smaller model, warm up Ollama once with `ollama run {OLLAMA_MODEL}`, "
            "or increase OLLAMA_READ_TIMEOUT_SECONDS.",
            504,
        ) from e
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        raise AiFilterError(f"Ollama returned HTTP {status}. Check OLLAMA_API and OLLAMA_MODEL.") from e
    except requests.RequestException as e:
        raise AiFilterError(
            f"Could not reach local Ollama at {endpoint}. Start Ollama and pull the configured model ({OLLAMA_MODEL})."
        ) from e

    progress("parsing", "Parsing Ollama JSON output")
    return parse_ai_delete_ids("".join(chunks), emails), "local-ollama"


def save_score(username: str, system_prompt: str, prompt: str, result: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO scores(username, system_prompt, prompt, score, tp, fp, fn, tn, deleted_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                system_prompt,
                prompt,
                result["score"],
                result["tp"],
                result["fp"],
                result["fn"],
                result["tn"],
                result["deleted_count"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        con.commit()


def build_reveal(result: dict[str, Any]) -> list[dict[str, Any]]:
    reveal = []
    detail_map = {d["id"]: d for d in result["details"]}
    for e in EMAILS:
        d = detail_map[e["id"]]
        if d["deleted"] or d["result"] == "FN":
            reveal.append({
                "id": e["id"],
                "sender": e["sender"],
                "subject": e["subject"],
                "result": d["result"],
                "is_malicious": e["is_malicious"],
                "indicators": e["indicators"],
            })
    return reveal


def score_result(delete_ids: list[int]) -> dict[str, Any]:
    delete_set = set(delete_ids)
    tp = fp = fn = tn = 0
    details = []
    for e in EMAILS:
        deleted = e["id"] in delete_set
        mal = e["is_malicious"]
        if deleted and mal:
            tp += 1
            result = "TP"
        elif deleted and not mal:
            fp += 1
            result = "FP"
        elif not deleted and mal:
            fn += 1
            result = "FN"
        else:
            tn += 1
            result = "TN"
        details.append({"id": e["id"], "result": result, "deleted": deleted, "is_malicious": mal})

    # FN is slightly more expensive because a malicious email survived.
    score = max(0, 1000 + tp * 5 + tn - fp * 45 - fn * 70)
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        "score": score,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "deleted_count": len(delete_set),
        "details": details,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/emails")
def api_emails():
    safe_emails = []
    for e in EMAILS:
        item = dict(e)
        # Keep answer hidden from the main user flow. Revealed only after scoring.
        item.pop("is_malicious", None)
        item.pop("indicators", None)
        safe_emails.append(item)
    return jsonify({"emails": safe_emails, "total": len(safe_emails)})


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON request body is required"}), 400
    username = (data.get("username") or "anonymous").strip()[:30]
    system_prompt = (data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    prompt = (data.get("prompt") or "").strip()
    if not system_prompt:
        return jsonify({"error": "system prompt is required"}), 400
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    try:
        delete_ids, engine = call_ollama(system_prompt, prompt, EMAILS)
    except AiFilterError as e:
        return jsonify({"error": str(e)}), e.status_code

    result = score_result(delete_ids)
    save_score(username, system_prompt, prompt, result)

    return jsonify({
        "engine": engine,
        "delete_ids": delete_ids,
        "result": result,
        "reveal": build_reveal(result),
    })


@sock.route("/ws/run")
def ws_run(ws):
    def send_event(event_type: str, **payload: Any) -> None:
        ws.send(json.dumps({"type": event_type, **payload}, ensure_ascii=False))

    try:
        raw = ws.receive(timeout=10)
        data = json.loads(raw) if raw else None
        if not isinstance(data, dict):
            send_event("error", error="JSON request body is required")
            return

        username = (data.get("username") or "anonymous").strip()[:30]
        system_prompt = (data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
        prompt = (data.get("prompt") or "").strip()
        if not system_prompt:
            send_event("error", error="system prompt is required")
            return
        if not prompt:
            send_event("error", error="prompt is required")
            return

        send_event("progress", stage="queued", message="Request received")

        def progress(stage: str, message: str) -> None:
            send_event("progress", stage=stage, message=message)

        delete_ids, engine = call_ollama_streaming(system_prompt, prompt, EMAILS, progress)
        send_event("progress", stage="scoring", message=f"Scoring {len(delete_ids)} deleted emails")

        result = score_result(delete_ids)
        save_score(username, system_prompt, prompt, result)
        send_event("progress", stage="saved", message="Score saved to leaderboard")

        send_event(
            "final",
            engine=engine,
            delete_ids=delete_ids,
            result=result,
            reveal=build_reveal(result),
        )
    except AiFilterError as e:
        send_event("error", error=str(e))
    except json.JSONDecodeError:
        send_event("error", error="WebSocket message must be valid JSON")
    except Exception as e:
        send_event("error", error=f"Unexpected server error: {e}")


@app.route("/api/leaderboard")
def api_leaderboard():
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT username, score, tp, fp, fn, tn, deleted_count, created_at
            FROM scores
            ORDER BY score DESC, fn ASC, fp ASC, created_at ASC
            LIMIT 20
            """
        ).fetchall()
    return jsonify({"leaderboard": [dict(r) for r in rows]})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=True)
