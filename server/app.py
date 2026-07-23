import json
import logging
import threading
from contextlib import contextmanager
from typing import Any

from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

from .config import DEFAULT_SYSTEM_PROMPT, PROJECT_ROOT, SERVER_DEBUG, SERVER_PORT
from .email_data import load_emails
from .errors import AiFilterError
from .ollama_client import call_ollama, call_ollama_streaming, ollama_endpoints
from .scoring import build_reveal, score_result
from .storage import init_db, leaderboard_rows, save_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=str(PROJECT_ROOT / "static"),
    template_folder=str(PROJECT_ROOT / "templates"),
)
sock = Sock(app)
EMAILS = load_emails()

# The answers never leave the server; strip them once instead of on every request.
PUBLIC_EMAILS = [
    {k: v for k, v in email.items() if k not in ("is_malicious", "indicators")}
    for email in EMAILS
]

# A whole class clicks "run" at once. Ollama can only work on so many prompts at a
# time, and piling more on top makes everyone slower, so runs queue here and waiting
# players are told where they are in line instead of staring at a dead progress bar.
RUN_SLOTS = threading.BoundedSemaphore(len(ollama_endpoints()))
_queue_lock = threading.Lock()
_waiting = 0


@contextmanager
def run_slot(on_wait=None):
    global _waiting
    if RUN_SLOTS.acquire(blocking=False):
        acquired_immediately = True
    else:
        acquired_immediately = False
        with _queue_lock:
            _waiting += 1
            position = _waiting
        if on_wait:
            on_wait(position)
        RUN_SLOTS.acquire()
        with _queue_lock:
            _waiting -= 1
    try:
        yield acquired_immediately
    finally:
        RUN_SLOTS.release()


def normalize_run_payload(data: Any) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        raise ValueError("JSON request body is required")

    username = (data.get("username") or "anonymous").strip()[:30]
    system_prompt = (data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    prompt = (data.get("prompt") or "").strip()
    if not system_prompt:
        raise ValueError("system prompt is required")
    if not prompt:
        raise ValueError("prompt is required")
    return username, system_prompt, prompt


def build_run_response(engine: str, delete_ids: list[int], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": engine,
        "delete_ids": delete_ids,
        "result": result,
        "reveal": build_reveal(result, EMAILS),
    }


@app.route("/")
def index():
    # Served from config so the textarea default cannot drift from the server default.
    return render_template("index.html", default_system_prompt=DEFAULT_SYSTEM_PROMPT)


@app.route("/api/emails")
def api_emails():
    return jsonify({"emails": PUBLIC_EMAILS, "total": len(PUBLIC_EMAILS)})


@app.route("/api/run", methods=["POST"])
def api_run():
    try:
        username, system_prompt, prompt = normalize_run_payload(request.get_json(silent=True))
        with run_slot():
            delete_ids, engine = call_ollama(system_prompt, prompt, EMAILS)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except AiFilterError as e:
        return jsonify({"error": str(e)}), e.status_code

    result = score_result(delete_ids, EMAILS)
    save_score(username, system_prompt, prompt, result)
    return jsonify(build_run_response(engine, delete_ids, result))


@sock.route("/ws/run")
def ws_run(ws):
    def send_event(event_type: str, **payload: Any) -> None:
        ws.send(json.dumps({"type": event_type, **payload}, ensure_ascii=False))

    try:
        raw = ws.receive(timeout=10)
        username, system_prompt, prompt = normalize_run_payload(json.loads(raw) if raw else None)
        send_event("progress", stage="queued", message="Request received")

        def progress(stage: str, message: str, **extra: Any) -> None:
            send_event("progress", stage=stage, message=message, **extra)

        def announce_wait(position: int) -> None:
            send_event("progress", stage="waiting_turn",
                       message=f"Another run is using the model; you are #{position} in line",
                       position=position)

        with run_slot(announce_wait):
            delete_ids, engine = call_ollama_streaming(system_prompt, prompt, EMAILS, progress)

        send_event("progress", stage="scoring", message=f"Scoring {len(delete_ids)} deleted emails")
        result = score_result(delete_ids, EMAILS)
        save_score(username, system_prompt, prompt, result)
        send_event("progress", stage="saved", message="Score saved to leaderboard")
        send_event("final", **build_run_response(engine, delete_ids, result))
    except ValueError as e:
        send_event("error", error=str(e))
    except AiFilterError as e:
        send_event("error", error=str(e))
    except json.JSONDecodeError:
        send_event("error", error="WebSocket message must be valid JSON")
    except Exception as e:
        # Losing the traceback here would leave nothing to debug from.
        logger.exception("Unexpected error during WebSocket run")
        send_event("error", error=f"Unexpected server error: {e}")


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify({"leaderboard": leaderboard_rows()})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=SERVER_DEBUG)
