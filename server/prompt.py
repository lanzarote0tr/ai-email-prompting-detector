"""Turning a batch of emails into an Ollama request payload."""

from typing import Any

from .config import (
    OLLAMA_BATCH_SIZE,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_THINK,
)

# Rough chars-per-token for this dataset's mixed Korean/ASCII text, measured against
# Ollama's own prompt_eval_count. Only used to warn before a prompt overflows num_ctx.
CHARS_PER_TOKEN = 2


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


def email_id_range(emails: list[dict[str, Any]]) -> str:
    ids = [email["id"] for email in emails]
    if not ids:
        return "empty"
    return f"{ids[0]}-{ids[-1]} ({len(ids)} emails)"


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


def estimated_prompt_tokens(system_prompt: str, user_prompt: str, batch: list[dict[str, Any]]) -> int:
    payload = build_payload(system_prompt, user_prompt, batch, stream=False)
    return len(payload["prompt"]) // CHARS_PER_TOKEN


def overflows_context(system_prompt: str, user_prompt: str, batch: list[dict[str, Any]]) -> int | None:
    """Estimated token count when a batch is at risk of being truncated, else None.

    Ollama silently drops the front of an over-long prompt, so the model answers about
    emails it never saw. Callers warn rather than fail, since the estimate is rough.
    """
    tokens = estimated_prompt_tokens(system_prompt, user_prompt, batch)
    return tokens if tokens > OLLAMA_NUM_CTX * 0.8 else None
