from typing import Any

PERFECT_SCORE = 1000


def penalties(malicious: int, benign: int) -> tuple[float, float]:
    """Cost of one FP and one FN, derived from the round itself.

    Missing every malicious email scores 0, and deleting every normal email scores 0.
    That fixes both penalties: one FN costs 1/malicious of the total, one FP costs
    1/benign. No hand-tuned constants, so changing ROUND_SIZE or the malicious ratio
    needs no recalibration.

    Because malicious mail is the minority (21% here), an FN lands ~4x harder than an
    FP on its own — the "missing an attack is worse" intent, without a magic number.
    """
    fp_penalty = PERFECT_SCORE / benign if benign else 0
    fn_penalty = PERFECT_SCORE / malicious if malicious else 0
    return fp_penalty, fn_penalty


def build_reveal(result: dict[str, Any], emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reveal = []
    detail_map = {d["id"]: d for d in result["details"]}
    for email in emails:
        detail = detail_map[email["id"]]
        if detail["deleted"] or detail["result"] == "FN":
            reveal.append({
                "id": email["id"],
                "sender": email["sender"],
                "subject": email["subject"],
                "result": detail["result"],
                "is_malicious": email["is_malicious"],
                "indicators": email["indicators"],
            })
    return reveal


def score_result(delete_ids: list[int], emails: list[dict[str, Any]]) -> dict[str, Any]:
    delete_set = set(delete_ids)
    tp = fp = fn = tn = 0
    details = []
    for email in emails:
        deleted = email["id"] in delete_set
        malicious = email["is_malicious"]
        if deleted and malicious:
            tp += 1
            result = "TP"
        elif deleted and not malicious:
            fp += 1
            result = "FP"
        elif not deleted and malicious:
            fn += 1
            result = "FN"
        else:
            tn += 1
            result = "TN"
        details.append({"id": email["id"], "result": result, "deleted": deleted, "is_malicious": malicious})

    fp_penalty, fn_penalty = penalties(tp + fn, tn + fp)
    score = max(0, round(PERFECT_SCORE - fp * fp_penalty - fn * fn_penalty))
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        "score": score,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "deleted_count": len(delete_set),
        "details": details,
    }
