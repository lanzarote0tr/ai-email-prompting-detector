"""Regression tests for the model-output parser.

No test runner needed:

    python -m tests.test_parsing
"""

import sys

from server.errors import AiFilterError
from server.ollama_client import parse_delete_ids

BATCH = [{"id": i} for i in range(1, 6)]

# (name, raw model output, expected delete ids)
PARSES = [
    ("plain object", '{"delete_ids": [4]}', [4]),
    ("empty list", '{"delete_ids": []}', []),
    ("markdown fence", '```json\n{"delete_ids": [2]}\n```', [2]),
    ("think tags stripped", "<think>maybe [1,2,3]</think>{\"delete_ids\": [5]}", [5]),
    ("alternate key", '{"malicious_ids": [3]}', [3]),
    ("wrapped answer", '{"result": {"delete_ids": [5]}}', [5]),
    ("ids in a string", '{"delete_ids": "2, 4"}', [2, 4]),
    ("bare array", "[1, 3]", [1, 3]),
    ("duplicates collapse", '{"delete_ids": [2, 2, 1]}', [1, 2]),
    # The verdict object must win over ids that merely appear in the prose first.
    ("prose ids before verdict", 'Emails [1, 2, 3] look fine. Final: {"delete_ids": [4]}', [4]),
    ("strings before verdict", 'Domains: ["pay.example"]\n{"delete_ids": [4]}', [4]),
    ("last verdict wins", '{"delete_ids": [1]}\nCorrection: {"delete_ids": [2, 3]}', [2, 3]),
    # A hallucinated id costs one email, never the whole run.
    ("id outside batch", '{"delete_ids": [4, 99]}', [4]),
    ("every id outside batch", '{"delete_ids": [99, 101]}', []),
    ("non-integer id", '{"delete_ids": [3, "spam"]}', [3]),
]

FAILURES = [
    ("empty output", ""),
    ("no json at all", "I cannot help with that."),
    ("json without ids", '{"status": "ok"}'),
]


def check(name: str, got, expected) -> bool:
    ok = got == expected
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (expected {expected!r})"))
    return ok


def main() -> int:
    results = []

    for name, raw, expected in PARSES:
        try:
            results.append(check(name, parse_delete_ids(raw, BATCH), expected))
        except AiFilterError as e:
            results.append(check(name, f"AiFilterError: {e}", expected))

    for name, raw in FAILURES:
        try:
            parse_delete_ids(raw, BATCH)
            results.append(check(name, "no error", "AiFilterError"))
        except AiFilterError as e:
            results.append(check(name, "AiFilterError" if e.retryable else "not retryable", "AiFilterError"))

    results.append(check("split retry recovers", *split_retry_case()))
    results.append(check("connection error is not retried", *no_retry_case()))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


def split_retry_case():
    """A batch the model cannot answer is halved until it can."""
    import server.ollama_client as oc

    original = oc.request_batch
    emails = [{"id": i} for i in range(1, 9)]
    try:
        oc.request_batch = lambda s, u, batch, stream: (
            ("garbage", "") if len(batch) > 2 else ('{"delete_ids": [%d]}' % batch[0]["id"], "")
        )
        return oc.analyze_batch("s", "u", emails, "1/1", False, splits_left=2), [1, 3, 5, 7]
    finally:
        oc.request_batch = original


def no_retry_case():
    """Ollama being unreachable fails fast instead of splitting the batch."""
    import server.ollama_client as oc

    original = oc.request_batch
    calls = []

    def down(*args, **kwargs):
        calls.append(1)
        raise AiFilterError("Could not reach local Ollama", retryable=False)

    try:
        oc.request_batch = down
        oc.analyze_batch("s", "u", [{"id": i} for i in range(1, 9)], "1/1", False, splits_left=3)
        return "no error", "1 attempt"
    except AiFilterError:
        return f"{len(calls)} attempt", "1 attempt"
    finally:
        oc.request_batch = original


if __name__ == "__main__":
    sys.exit(main())
