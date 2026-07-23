import json
from typing import Any

from .config import EMAILS_PATH


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

    return sorted(normalized, key=lambda e: e["id"])
