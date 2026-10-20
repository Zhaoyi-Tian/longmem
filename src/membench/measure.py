"""事后分析：只读 trace，不进入世界本身。"""

from collections import Counter


def bucket(age: int | None) -> str:
    if age is None:
        return "未听过"
    for hi, name in ((10, "<10"), (100, "10–99"), (1000, "100–999")):
        if age < hi:
            return name
    return "≥1000"


def summary(trace: list[dict], chapters: int) -> dict:
    """主指标是走出的章数。正确率只算答案已经交到手里的那些回答（急躁的开口单独计数），
    再按距离、跳数切片。"""
    kinds = Counter(e["kind"] for e in trace)
    by_age: dict[str, Counter] = {}
    by_hops: dict[int, Counter] = {}
    for e in trace:
        if e["kind"] == "premature":
            continue
        if e["kind"] == "ok":
            n = e["need"][e["word"]]
            age, h = n["age"], n["hops"]
        else:   # 错的那次，按最难想起的那个词算
            age = max((n["age"] for n in e["need"].values() if n["age"] is not None), default=None)
            h = max(n["hops"] for n in e["need"].values())
        by_age.setdefault(bucket(age), Counter())[e["kind"]] += 1
        by_hops.setdefault(h, Counter())[e["kind"]] += 1

    def acc(c: Counter) -> float | None:
        n = sum(c.values())
        return round(c["ok"] / n, 3) if n else None

    answered = Counter({k: v for k, v in kinds.items() if k != "premature"})
    first = first_tries(trace)
    return {
        "chapters": chapters,
        "first_try": acc(Counter(e["kind"] for e in first)),
        "first_try_by_nights": {k: acc(Counter(e["kind"] for e in first if night_bucket(e) == k))
                                for k in ("当夜", "隔夜")},
        "says": len(trace),
        "premature": kinds["premature"],
        "accuracy": acc(answered),
        "errors": {k: v for k, v in kinds.items() if k not in ("ok", "premature")},
        "accuracy_by_age": {k: acc(c) for k, c in by_age.items()},
        "accuracy_by_hops": {k: acc(c) for k, c in sorted(by_hops.items())},
    }


def first_tries(trace: list[dict]) -> list[dict]:
    """每道门（同一个人、同一版要求）第一次正式回答。之后的尝试可能是在乱猜，不算。"""
    seen, out = set(), []
    for e in trace:
        key = (e["who"], e["version"])
        if e["kind"] != "premature" and key not in seen:
            seen.add(key)
            out.append(e)
    return out


def night_bucket(e: dict) -> str:
    """要的词里最早的那个，是不是在之前的夜里听到的。"""
    nights = [n["nights"] for n in e["need"].values() if n.get("nights") is not None]
    return "隔夜" if nights and max(nights) > 0 else "当夜"
