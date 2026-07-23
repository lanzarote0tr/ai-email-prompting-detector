"""Recovering a list of email ids from whatever the model actually wrote.

Small local models wrap the answer in prose, fence it in markdown, leave `<think>`
tags behind, rename the key, or quote the numbers. Everything here exists because a
model did it, so each helper is deliberately forgiving — but never at the cost of
picking up ids the model only mentioned in passing.
"""

import json
import logging
import re
from typing import Any

from .errors import AiFilterError

logger = logging.getLogger(__name__)

DELETE_ID_KEYS = ("delete_ids", "deleted_ids", "ids", "delete", "malicious_ids")


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
    """Drop inline <think>...</think> blocks some models emit despite think=False."""
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
    """The balanced {...} or [...] beginning at `start`, or None if it never closes."""
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


def delete_id_key(parsed: dict[str, Any]) -> str | None:
    for key in DELETE_ID_KEYS:
        if parsed.get(key) is not None:
            return key
    return None


def clean_json_text(content: str) -> str:
    """Pick the JSON value most likely to be the model's actual verdict.

    Models mention ids in prose before deciding ("emails [1, 2] look fine"), so an
    object carrying a delete-ids key beats a bare array, and a later verdict beats an
    earlier one. Getting this order wrong silently deletes the emails the model just
    called safe.
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
    """Model output -> the ids from `emails` it wants deleted.

    Raises AiFilterError (retryable) when there is no usable answer at all.
    """
    if not isinstance(content, str) or not content.strip():
        raise AiFilterError("AI API response did not contain a text response.", retryable=True)

    cleaned = clean_json_text(content)
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
    return sorted(set(delete_ids))
