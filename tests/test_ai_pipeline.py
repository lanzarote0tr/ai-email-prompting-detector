"""Regression tests for the AI pipeline: output parsing, batch retry, host dispatch.

No test runner needed:

    python -m tests.test_ai_pipeline
"""

import sys
import time

from server.errors import AiFilterError
from server.parsing import parse_delete_ids

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
    results.append(check("batches spread over hosts", *multi_host_case()))
    results.append(check("dead host fails over", *failover_case()))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


def split_retry_case():
    """A batch the model cannot answer is halved until it can."""
    import server.ollama_client as oc

    original = oc.request_batch
    emails = [{"id": i} for i in range(1, 9)]
    try:
        oc.request_batch = lambda s, u, batch, stream, endpoint=None: (
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


def fake_emails(n: int) -> list[dict]:
    return [{"id": i, "sender": "s", "subject": "x", "attachment": "", "body": "b"} for i in range(1, n + 1)]


def multi_host_case():
    """Every batch runs somewhere, and the work is shared rather than piled on one host."""
    import threading

    import server.ollama_client as oc

    original, hosts = oc.request_batch, oc.ollama_endpoints
    seen: dict[str, int] = {}
    lock = threading.Lock()

    def fake(s, u, batch, stream, endpoint=None):
        with lock:
            seen[endpoint] = seen.get(endpoint, 0) + 1
        # A real call takes seconds; without a pause the first worker drains the
        # queue before the others have even started and nothing looks distributed.
        time.sleep(0.05)
        return '{"delete_ids": [%d]}' % batch[0]["id"], ""

    try:
        oc.ollama_endpoints = lambda: ["http://a/generate", "http://b/generate", "http://c/generate"]
        oc.request_batch = fake
        ids, _ = oc.run_batches("s", "u", fake_emails(125), stream=False)
        # 5 batches of 25, every id accounted for, and more than one host used.
        spread = len(seen) > 1 and sum(seen.values()) == 5
        return (sorted(ids), spread), ([1, 26, 51, 76, 101], True)
    finally:
        oc.request_batch, oc.ollama_endpoints = original, hosts


def failover_case():
    """A host that is down must not lose its batches — a live host picks them up."""
    import server.ollama_client as oc

    original, hosts = oc.request_batch, oc.ollama_endpoints

    def flaky(s, u, batch, stream, endpoint=None):
        if "dead" in endpoint:
            raise AiFilterError("Could not reach Ollama", retryable=False)
        return '{"delete_ids": [%d]}' % batch[0]["id"], ""

    try:
        oc.ollama_endpoints = lambda: ["http://dead/generate", "http://live/generate"]
        oc.request_batch = flaky
        ids, _ = oc.run_batches("s", "u", fake_emails(125), stream=False)
        return sorted(ids), [1, 26, 51, 76, 101]
    finally:
        oc.request_batch, oc.ollama_endpoints = original, hosts


if __name__ == "__main__":
    sys.exit(main())
