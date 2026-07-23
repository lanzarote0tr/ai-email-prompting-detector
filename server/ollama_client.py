"""Talking to Ollama: one request per batch, spread over however many hosts exist.

Splitting a run across hosts is the only parallelism that pays. Concurrent requests
to a *single* Ollama gain nothing — measured on an M1 Pro, four concurrent batches
finish in the same wall time as four sequential ones, because one GPU is already
saturated. Extra machines each bring their own GPU and memory bandwidth.
"""

import json
import logging
import queue
import threading
from typing import Any

import requests

from .config import (
    AI_DEBUG_LOGS,
    AI_DEBUG_OUTPUT_CHARS,
    OLLAMA_API,
    OLLAMA_API_KEY,
    OLLAMA_APIS,
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
from .parsing import ensure_text, parse_delete_ids
from .prompt import build_payload, email_batches, email_id_range, overflows_context

logger = logging.getLogger(__name__)

ENGINE_NAME = "local-ollama"


def debug_log(message: str, *args: Any) -> None:
    if AI_DEBUG_LOGS:
        logger.info(message, *args)


def preview_text(value: Any) -> str:
    text = "" if value is None else ensure_text(value) if isinstance(value, bytes) else str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > AI_DEBUG_OUTPUT_CHARS:
        return text[:AI_DEBUG_OUTPUT_CHARS] + "...[truncated]"
    return text


# ----------------------------------------------------------------- transport

def normalize_endpoint(api: str) -> str:
    endpoint = api.rstrip("/")
    if not endpoint.endswith("/generate"):
        endpoint += "/generate"
    return endpoint


def ollama_endpoints() -> list[str]:
    return [normalize_endpoint(api) for api in OLLAMA_APIS] or [normalize_endpoint(OLLAMA_API)]


def ollama_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def response_content(data: dict[str, Any]) -> str:
    response = data.get("response")
    return response if isinstance(response, str) else ""


def read_stream(resp) -> tuple[str, str]:
    chunks = []
    thinking_chunks = []
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


def request_batch(
    system_prompt: str,
    user_prompt: str,
    batch: list[dict[str, Any]],
    stream: bool,
    endpoint: str | None = None,
) -> tuple[str, str]:
    """Send one batch to one Ollama host and return its (response, thinking) text."""
    endpoint = endpoint or ollama_endpoints()[0]
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
            return response_content(data), thinking if isinstance(thinking, str) else ""

        with requests.post(
            endpoint, headers=ollama_headers(), json=payload, timeout=OLLAMA_TIMEOUT, stream=True
        ) as resp:
            resp.raise_for_status()
            return read_stream(resp)
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
            f"Could not reach Ollama at {endpoint}. Start it and pull the configured model ({OLLAMA_MODEL})."
        ) from e
    except (ValueError, json.JSONDecodeError) as e:
        raise AiFilterError(f"AI API returned invalid JSON response: {e}", retryable=True) from e


# -------------------------------------------------------------- orchestration

def analyze_batch(
    system_prompt: str,
    user_prompt: str,
    batch: list[dict[str, Any]],
    label: str,
    stream: bool,
    splits_left: int = OLLAMA_BATCH_RETRIES,
    endpoint: str | None = None,
) -> list[int]:
    """Classify one batch, halving it and retrying if the model's answer is unusable.

    Re-asking with the identical prompt is pointless at temperature 0 — the model
    repeats itself — so a retry splits the batch, which is also the fix when the
    answer was truncated for being too long.
    """
    try:
        response_text, thinking_text = request_batch(system_prompt, user_prompt, batch, stream, endpoint)
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
            analyze_batch(system_prompt, user_prompt, batch[:mid], f"{label}a", stream, splits_left - 1, endpoint)
            + analyze_batch(system_prompt, user_prompt, batch[mid:], f"{label}b", stream, splits_left - 1, endpoint)
        )


def run_batches(
    system_prompt: str,
    user_prompt: str,
    emails: list[dict[str, Any]],
    stream: bool,
    progress=None,
) -> tuple[list[int], str]:
    batches = email_batches(emails)
    endpoints = ollama_endpoints()
    total = len(batches)

    debug_log(
        "AI run start model=%s hosts=%d emails=%d batches=%d batch_size=%d num_ctx=%d num_predict=%d think=%s",
        OLLAMA_MODEL, len(endpoints), len(emails), total,
        OLLAMA_BATCH_SIZE, OLLAMA_NUM_CTX, OLLAMA_NUM_PREDICT, OLLAMA_THINK,
    )
    if batches:
        oversized = overflows_context(system_prompt, user_prompt, batches[0])
        if oversized:
            logger.warning(
                "Batch prompt is roughly %d tokens against num_ctx=%d; lower OLLAMA_BATCH_SIZE "
                "or raise OLLAMA_NUM_CTX or the model will not see every email.",
                oversized, OLLAMA_NUM_CTX,
            )

    state = threading.Lock()

    def report(stage: str, message: str, **extra: Any) -> None:
        if progress:
            with state:
                progress(stage, message, **extra)

    where = endpoints[0] if len(endpoints) == 1 else f"{len(endpoints)} Ollama hosts"
    report("connecting", f"Connecting to {where}", total=total)
    report("waiting", f"Waiting for {OLLAMA_MODEL}; read timeout is {OLLAMA_READ_TIMEOUT_SECONDS}s.", total=total)

    pending: queue.Queue = queue.Queue()
    for batch_number, batch in enumerate(batches, start=1):
        pending.put((batch_number, batch))

    delete_ids: list[int] = []
    errors: list[AiFilterError] = []
    done = 0

    def run_one(batch_number: int, batch: list[dict[str, Any]], home: str) -> list[int]:
        """Run a batch on `home`, falling back to the other hosts if that one is down."""
        label = f"{batch_number}/{total}"
        candidates = [home] + [e for e in endpoints if e != home]
        for attempt, endpoint in enumerate(candidates):
            report("generating", f"Analyzing batch {label} on {endpoint}", index=batch_number, total=total)
            try:
                return analyze_batch(system_prompt, user_prompt, batch, label, stream, endpoint=endpoint)
            except AiFilterError as e:
                # An unreachable host is another machine's problem to pick up. A bad
                # *answer* is the model's fault and would repeat everywhere, so it stands.
                if e.retryable or attempt == len(candidates) - 1:
                    raise
                logger.warning("Host %s failed batch %s (%s); trying another host", endpoint, label, e)
        raise AssertionError("unreachable")

    def worker(home: str) -> None:
        nonlocal done
        while not errors:
            try:
                batch_number, batch = pending.get_nowait()
            except queue.Empty:
                return
            try:
                found = run_one(batch_number, batch, home)
            except AiFilterError as e:
                errors.append(e)
                return
            with state:
                delete_ids.extend(found)
                done += 1
                finished, deleted_now = done, len(set(delete_ids))
            report("parsed", f"Finished batch {finished}/{total}",
                   index=finished, total=total, deleted=deleted_now)

    if len(endpoints) == 1:
        worker(endpoints[0])
    else:
        threads = [threading.Thread(target=worker, args=(e,), daemon=True) for e in endpoints]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    if errors:
        raise errors[0]
    return sorted(set(delete_ids)), ENGINE_NAME


def call_ollama(system_prompt: str, user_prompt: str, emails: list[dict[str, Any]]) -> tuple[list[int], str]:
    return run_batches(system_prompt, user_prompt, emails, stream=False)


def call_ollama_streaming(
    system_prompt: str, user_prompt: str, emails: list[dict[str, Any]], progress
) -> tuple[list[int], str]:
    return run_batches(system_prompt, user_prompt, emails, stream=True, progress=progress)
