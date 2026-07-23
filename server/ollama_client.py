import json
from typing import Any

import requests

from .config import (
    OLLAMA_API,
    OLLAMA_API_KEY,
    OLLAMA_BATCH_SIZE,
    OLLAMA_CONNECT_TIMEOUT_SECONDS,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_OUTPUT_SCHEMA,
    OLLAMA_READ_TIMEOUT_SECONDS,
    OLLAMA_TIMEOUT,
)
from .errors import AiFilterError


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def email_batches(emails: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [emails[i:i + OLLAMA_BATCH_SIZE] for i in range(0, len(emails), OLLAMA_BATCH_SIZE)]


def format_emails(emails: list[dict[str, Any]]) -> str:
    lines = ["Emails, one per line:", "id | sender | subject | attachment | body"]
    for email in emails:
        lines.append(
            " | ".join(
                [
                    str(email["id"]),
                    compact_text(email["sender"]),
                    compact_text(email["subject"]),
                    compact_text(email["attachment"]),
                    compact_text(email["body"]),
                ]
            )
        )
    return "\n".join(lines)


def ollama_endpoint() -> str:
    endpoint = OLLAMA_API.rstrip("/")
    if not endpoint.endswith("/generate"):
        endpoint += "/generate"
    return endpoint


def ollama_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def build_payload(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
    allowed_ids = ", ".join(str(email["id"]) for email in emails)
    return {
        "model": OLLAMA_MODEL,
        "stream": stream,
        "format": OLLAMA_OUTPUT_SCHEMA,
        "system": system_prompt,
        "options": {
            "temperature": 0,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
        "prompt": (
            "/no_think\n\n"
            "Task: classify only the emails in this batch.\n"
            f"Allowed delete_ids: {allowed_ids}\n"
            'If no listed email matches the rule, return exactly {"delete_ids":[]}.\n\n'
            "User detection prompt:\n"
            + user_prompt
            + "\n\n"
            + format_emails(emails)
            + "\n\nReturn one strict JSON object only. Use only allowed delete_ids."
        ),
    }


def clean_json_text(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    lower = content.lower()
    while "<think>" in lower:
        start = lower.find("<think>")
        end = lower.find("</think>", start)
        if end == -1:
            content = content[:start].strip()
            break
        content = content[:start] + content[end + len("</think>"):]
        lower = content.lower()

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        return content[start:end + 1]
    return content


def parse_delete_ids(content: str | None, emails: list[dict[str, Any]]) -> list[int]:
    if not isinstance(content, str):
        raise AiFilterError("AI API response did not contain a text response.")
    try:
        parsed = json.loads(clean_json_text(content))
    except json.JSONDecodeError as e:
        snippet = content.strip().replace("\n", " ")[:300]
        raise AiFilterError(
            'AI output must be valid JSON like {"delete_ids": [1, 2, 3]}. '
            f"Raw output starts with: {snippet!r}"
        ) from e

    if not isinstance(parsed, dict) or not isinstance(parsed.get("delete_ids"), list):
        raise AiFilterError('AI output must be a JSON object with a "delete_ids" list.')

    allowed_ids = {email["id"] for email in emails}
    delete_ids = []
    for raw_id in parsed["delete_ids"]:
        try:
            email_id = int(raw_id)
        except (TypeError, ValueError) as e:
            raise AiFilterError(f"AI returned a non-integer email id: {raw_id!r}") from e
        if email_id not in allowed_ids:
            raise AiFilterError(f"AI returned unknown email id: {email_id}")
        delete_ids.append(email_id)
    return sorted(set(delete_ids))


def call_ollama(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]]) -> tuple[list[int], str]:
    endpoint = ollama_endpoint()
    delete_ids = []

    for batch in email_batches(emails):
        try:
            resp = requests.post(
                endpoint,
                headers=ollama_headers(),
                json=build_payload(system_prompt, user_prompt, batch, stream=False),
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
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

        if not isinstance(data, dict):
            raise AiFilterError("AI API returned invalid JSON response: top-level response must be an object.")
        delete_ids.extend(parse_delete_ids(data.get("response"), batch))

    return sorted(set(delete_ids)), "local-ollama"


def call_ollama_streaming(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]], progress) -> tuple[list[int], str]:
    endpoint = ollama_endpoint()
    batches = email_batches(emails)
    delete_ids = []
    progress("connecting", f"Connecting to local Ollama at {endpoint}")
    progress("waiting", f"Waiting for {OLLAMA_MODEL}; read timeout is {OLLAMA_READ_TIMEOUT_SECONDS}s.")

    for batch_number, batch in enumerate(batches, start=1):
        batch_label = f"{batch_number}/{len(batches)}"
        chunks = []
        try:
            with requests.post(
                endpoint,
                headers=ollama_headers(),
                json=build_payload(system_prompt, user_prompt, batch, stream=True),
                timeout=OLLAMA_TIMEOUT,
                stream=True,
            ) as resp:
                resp.raise_for_status()
                progress("generating", f"Ollama is analyzing batch {batch_label} with {OLLAMA_MODEL}")
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise AiFilterError("Ollama stream returned a non-object event.")
                    token = event.get("response")
                    if isinstance(token, str):
                        chunks.append(token)
                    if event.get("done"):
                        break
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
        except (ValueError, json.JSONDecodeError) as e:
            raise AiFilterError(f"Ollama stream returned invalid JSON: {e}") from e

        progress("parsing", f"Parsing batch {batch_label}")
        delete_ids.extend(parse_delete_ids("".join(chunks), batch))

    return sorted(set(delete_ids)), "local-ollama"
