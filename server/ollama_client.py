import json
import logging
import re
from typing import Any

import requests

from .config import (
    AI_DEBUG_LOGS,
    AI_DEBUG_OUTPUT_CHARS,
    OLLAMA_API,
    OLLAMA_API_KEY,
    OLLAMA_BATCH_RETRIES,
    OLLAMA_BATCH_SIZE,
    OLLAMA_CONNECT_TIMEOUT_SECONDS,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_READ_TIMEOUT_SECONDS,
    OLLAMA_THINK,
    OLLAMA_TIMEOUT,
)
from .errors import AiFilterError

logger = logging.getLogger(__name__)


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
        "think": OLLAMA_THINK,
        "system": system_prompt,
        "options": {
            "temperature": 0,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
        "prompt": (
            "Task: classify only the emails in this batch.\n"
            f"Allowed delete_ids: {allowed_ids}\n"
            'If no listed email matches the rule, return exactly {"delete_ids":[]}.\n\n'
            "User detection prompt:\n"
            + user_prompt
            + "\n\n"
            + format_emails(emails)
            + "\n\nDo not write a per-email analysis. "
            + "The final response must contain one JSON object only, "
            + "using only the allowed delete_ids."
        ),
    }


def debug_log(message: str, *args: Any) -> None:
    if AI_DEBUG_LOGS:
        logger.info(message, *args)


def preview_text(value: Any) -> str:
    text = "" if value is None else ensure_text(value) if isinstance(value, bytes) else str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > AI_DEBUG_OUTPUT_CHARS:
        return text[:AI_DEBUG_OUTPUT_CHARS] + "...[truncated]"
    return text


def email_id_range(emails: list[dict[str, Any]]) -> str:
    ids = [email["id"] for email in emails]
    if not ids:
        return "empty"
    return f"{ids[0]}-{ids[-1]} ({len(ids)} emails)"


def ensure_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def strip_markdown_fence(content: str) -> str:
    content = content.strip()
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def remove_thinking(content: str) -> str:
    lower = content.lower()
    while "<think>" in lower:
        start = lower.find("<think>")
        end = lower.find("</think>", start)
        if end == -1:
            return content[:start].strip()
        content = content[:start] + content[end + len("</think>"):]
        lower = content.lower()
    return content.strip()


def balanced_json_slice(content: str, start: int) -> str | None:
    opener = content[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(content)):
        current = content[idx]
        if in_string:
            if escape:
                escape = False
            elif current == "\\":
                escape = True
            elif current == '"':
                in_string = False
            continue

        if current == '"':
            in_string = True
        elif current == opener:
            depth += 1
        elif current == closer:
            depth -= 1
            if depth == 0:
                return content[start:idx + 1]
    return None


def json_candidates(content: str) -> list[tuple[str, Any]]:
    """Every balanced JSON object/array in the text, in order, with its parsed value."""
    found = []
    idx = 0
    while idx < len(content):
        if content[idx] not in "[{":
            idx += 1
            continue
        candidate = balanced_json_slice(content, idx)
        if candidate is None:
            idx += 1
            continue
        try:
            found.append((candidate, json.loads(candidate)))
        except json.JSONDecodeError:
            idx += 1
            continue
        idx += len(candidate)
    return found


def clean_json_text(content: str) -> str:
    """Pick the JSON value most likely to be the model's answer.

    Models often mention ids in prose (``emails [1, 2] look fine``) before the real
    verdict, so an object carrying a delete-ids key always wins over a bare array,
    and the last such object wins over earlier ones.
    """
    cleaned = remove_thinking(strip_markdown_fence(content))
    candidates = json_candidates(cleaned)
    if not candidates:
        return cleaned

    keyed = [text for text, parsed in candidates if isinstance(parsed, dict) and delete_id_key(parsed)]
    if keyed:
        return keyed[-1]
    objects = [text for text, parsed in candidates if isinstance(parsed, dict)]
    if objects:
        return objects[-1]
    return candidates[-1][0]


DELETE_ID_KEYS = ("delete_ids", "deleted_ids", "ids", "delete", "malicious_ids")


def delete_id_key(parsed: dict[str, Any]) -> str | None:
    for key in DELETE_ID_KEYS:
        if parsed.get(key) is not None:
            return key
    return None


def extract_delete_id_values(parsed: Any, depth: int = 2) -> Any:
    if isinstance(parsed, list):
        return parsed
    if not isinstance(parsed, dict):
        return None

    key = delete_id_key(parsed)
    if key:
        return parsed[key]
    if depth <= 0:
        return None
    # Models sometimes wrap the answer, e.g. {"result": {"delete_ids": [...]}}.
    for value in parsed.values():
        if isinstance(value, dict):
            nested = extract_delete_id_values(value, depth - 1)
            if nested is not None:
                return nested
    return None


def normalize_delete_id_values(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        numbers = re.findall(r"\d+", value)
        return numbers if numbers else None
    return None


def parse_delete_ids(content: str | None, emails: list[dict[str, Any]]) -> list[int]:
    if not isinstance(content, str) or not content.strip():
        raise AiFilterError("AI API response did not contain a text response.", retryable=True)
    cleaned = clean_json_text(content)
    debug_log("AI JSON candidate: %s", preview_text(cleaned))
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        snippet = content.strip().replace("\n", " ")[:300]
        raise AiFilterError(
            'AI output must be valid JSON like {"delete_ids": [1, 2, 3]}. '
            f"Raw output starts with: {snippet!r}",
            retryable=True,
        ) from e

    raw_delete_ids = normalize_delete_id_values(extract_delete_id_values(parsed))
    if raw_delete_ids is None:
        snippet = json.dumps(parsed, ensure_ascii=False)[:300]
        raise AiFilterError(
            'AI output must contain delete IDs, for example {"delete_ids": [1, 2, 3]}. '
            f"Parsed JSON was: {snippet!r}",
            retryable=True,
        )

    # An id the model invented, or one belonging to another batch, is a normal model
    # slip. Dropping it costs one email; failing the run throws away every batch
    # analyzed so far, so ignore it and keep going.
    allowed_ids = {email["id"] for email in emails}
    delete_ids = []
    ignored = []
    for raw_id in raw_delete_ids:
        try:
            email_id = int(raw_id)
        except (TypeError, ValueError):
            ignored.append(raw_id)
            continue
        if email_id not in allowed_ids:
            ignored.append(raw_id)
            continue
        delete_ids.append(email_id)

    if ignored:
        logger.warning("AI returned %d id(s) outside this batch; ignoring %s", len(ignored), ignored[:20])
    parsed_ids = sorted(set(delete_ids))
    debug_log("AI parsed delete_ids=%s", parsed_ids)
    return parsed_ids


def response_content(data: dict[str, Any]) -> str | None:
    response = data.get("response")
    return response if isinstance(response, str) else None


def request_batch(
    system_prompt: str,
    user_prompt: str,
    batch: list[dict[str, Any]],
    stream: bool,
) -> tuple[str, str]:
    """Send one batch to Ollama and return its (response, thinking) text."""
    endpoint = ollama_endpoint()
    payload = build_payload(system_prompt, user_prompt, batch, stream=stream)
    debug_log(
        "AI request ids=%s prompt_chars=%d stream=%s",
        email_id_range(batch),
        len(payload["prompt"]),
        str(stream).lower(),
    )
    try:
        if not stream:
            resp = requests.post(endpoint, headers=ollama_headers(), json=payload, timeout=OLLAMA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise AiFilterError(
                    "AI API returned invalid JSON response: top-level response must be an object.",
                    retryable=True,
                )
            thinking = data.get("thinking")
            return response_content(data) or "", thinking if isinstance(thinking, str) else ""

        chunks = []
        thinking_chunks = []
        with requests.post(
            endpoint,
            headers=ollama_headers(),
            json=payload,
            timeout=OLLAMA_TIMEOUT,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                event = json.loads(ensure_text(line))
                if not isinstance(event, dict):
                    raise AiFilterError("Ollama stream returned a non-object event.", retryable=True)
                token = event.get("response")
                if isinstance(token, str):
                    chunks.append(token)
                thinking = event.get("thinking")
                if isinstance(thinking, str):
                    thinking_chunks.append(thinking)
                if event.get("done"):
                    break
        return "".join(chunks).strip(), "".join(thinking_chunks).strip()
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
        raise AiFilterError(f"AI API returned invalid JSON response: {e}", retryable=True) from e


def analyze_batch(
    system_prompt: str,
    user_prompt: str,
    batch: list[dict[str, Any]],
    label: str,
    stream: bool,
    splits_left: int = OLLAMA_BATCH_RETRIES,
) -> list[int]:
    """Classify one batch, splitting it in half and retrying if the model's answer is unusable.

    Retrying the same batch is pointless at temperature 0 — the model would repeat itself —
    so a retry halves the batch instead, which is also the fix for a truncated answer.
    """
    try:
        response_text, thinking_text = request_batch(system_prompt, user_prompt, batch, stream)
        debug_log("AI batch %s raw output: %s", label, preview_text(response_text))
        if thinking_text.strip():
            debug_log("AI batch %s raw thinking: %s", label, preview_text(thinking_text))
        if not response_text.strip() and thinking_text.strip():
            raise AiFilterError(
                "AI produced thinking text but no final response. Increase OLLAMA_NUM_PREDICT, "
                "use a smaller OLLAMA_BATCH_SIZE, or set OLLAMA_THINK=0.",
                retryable=True,
            )
        return parse_delete_ids(response_text, batch)
    except AiFilterError as e:
        if not e.retryable or splits_left <= 0 or len(batch) < 2:
            raise
        mid = len(batch) // 2
        logger.warning("AI batch %s failed (%s); retrying as two smaller batches", label, e)
        return (
            analyze_batch(system_prompt, user_prompt, batch[:mid], f"{label}a", stream, splits_left - 1)
            + analyze_batch(system_prompt, user_prompt, batch[mid:], f"{label}b", stream, splits_left - 1)
        )


def run_batches(
    system_prompt: str,
    user_prompt: str,
    emails: list[dict[str, Any]],
    stream: bool,
    progress=None,
) -> tuple[list[int], str]:
    batches = email_batches(emails)
    total = len(batches)
    delete_ids = []
    debug_log(
        "AI run start model=%s endpoint=%s emails=%d batches=%d batch_size=%d num_ctx=%d num_predict=%d think=%s",
        OLLAMA_MODEL,
        ollama_endpoint(),
        len(emails),
        total,
        OLLAMA_BATCH_SIZE,
        OLLAMA_NUM_CTX,
        OLLAMA_NUM_PREDICT,
        OLLAMA_THINK,
    )
    if batches:
        # A prompt that overflows num_ctx is silently truncated by Ollama, so the model
        # answers about emails it never fully saw. Warn instead of failing mysteriously.
        estimated_tokens = len(build_payload(system_prompt, user_prompt, batches[0], stream)["prompt"]) // 2
        if estimated_tokens > OLLAMA_NUM_CTX * 0.8:
            logger.warning(
                "Batch prompt is roughly %d tokens against num_ctx=%d; lower OLLAMA_BATCH_SIZE "
                "or raise OLLAMA_NUM_CTX or the model will not see every email.",
                estimated_tokens,
                OLLAMA_NUM_CTX,
            )

    if progress:
        progress("connecting", f"Connecting to local Ollama at {ollama_endpoint()}", total=total)
        progress(
            "waiting",
            f"Waiting for {OLLAMA_MODEL}; read timeout is {OLLAMA_READ_TIMEOUT_SECONDS}s.",
            total=total,
        )

    for batch_number, batch in enumerate(batches, start=1):
        label = f"{batch_number}/{total}"
        if progress:
            progress(
                "generating",
                f"Ollama is analyzing batch {label} with {OLLAMA_MODEL}",
                index=batch_number,
                total=total,
            )
        delete_ids.extend(analyze_batch(system_prompt, user_prompt, batch, label, stream))
        if progress:
            progress(
                "parsed",
                f"Finished batch {label}",
                index=batch_number,
                total=total,
                deleted=len(set(delete_ids)),
            )

    return sorted(set(delete_ids)), "local-ollama"


def call_ollama(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]]) -> tuple[list[int], str]:
    return run_batches(system_prompt, user_prompt, emails, stream=False)


def call_ollama_streaming(
    system_prompt: str,
    user_prompt: str,
    emails: list[dict[str, Any]],
    progress,
) -> tuple[list[int], str]:
    return run_batches(system_prompt, user_prompt, emails, stream=True, progress=progress)
