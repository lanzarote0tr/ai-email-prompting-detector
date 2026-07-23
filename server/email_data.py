import json
import random
from typing import Any

from .config import EMAILS_PATH, ROUND_SEED, ROUND_SIZE


def load_emails() -> list[dict[str, Any]]:
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

    return build_round(sorted(normalized, key=lambda e: e["id"]))


def build_round(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the emails a single attempt is graded on.

    Run time is dominated by how many emails the model has to read, so the whole
    dataset is a pool and each round draws a fixed-size sample from it. The sample
    is seeded, so every player hitting this server sees and is scored on the same
    emails; change ROUND_SEED (or restart) to deal a new round.

    The malicious ratio of the pool is preserved, otherwise a round could come out
    with almost no malicious mail and the score would mean nothing.
    """
    if ROUND_SIZE <= 0 or ROUND_SIZE >= len(emails):
        return emails

    malicious = [e for e in emails if e["is_malicious"]]
    benign = [e for e in emails if not e["is_malicious"]]
    want_malicious = round(ROUND_SIZE * len(malicious) / len(emails))
    want_malicious = max(1, min(want_malicious, len(malicious), ROUND_SIZE - 1))

    rng = random.Random(ROUND_SEED)
    picked = rng.sample(malicious, want_malicious) + rng.sample(benign, ROUND_SIZE - want_malicious)
    return sorted(picked, key=lambda e: e["id"])
