import json
from typing import Any

from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

from .config import DEFAULT_SYSTEM_PROMPT, PROJECT_ROOT, SERVER_PORT
from .email_data import load_emails
from .errors import AiFilterError
from .ollama_client import call_ollama, call_ollama_streaming
from .scoring import build_reveal, score_result
from .storage import init_db, leaderboard_rows, save_score

app = Flask(
    __name__,
    static_folder=str(PROJECT_ROOT / "static"),
    template_folder=str(PROJECT_ROOT / "templates"),
)
sock = Sock(app)
EMAILS = load_emails()


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
    return render_template("index.html")


@app.route("/api/emails")
def api_emails():
    safe_emails = []
    for email in EMAILS:
        item = dict(email)
        item.pop("is_malicious", None)
        item.pop("indicators", None)
        safe_emails.append(item)
    return jsonify({"emails": safe_emails, "total": len(safe_emails)})


@app.route("/api/run", methods=["POST"])
def api_run():
    try:
        username, system_prompt, prompt = normalize_run_payload(request.get_json(silent=True))
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

        def progress(stage: str, message: str) -> None:
            send_event("progress", stage=stage, message=message)

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
        send_event("error", error=f"Unexpected server error: {e}")


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify({"leaderboard": leaderboard_rows()})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=True)
