#!/usr/bin/env python3
"""Probe /v1/rerank from inside Open WebUI (no host port). Expect the contract snippet first."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("RERANK_URL", "http://openwebui-rerank:8080/v1/rerank")
QUERY = "пункт 5.2 договора: срок оплаты"
DOCS = [
    "Погода в Москве завтра облачная, без осадков.",
    "Пункт 5.2. Оплата производится в течение 10 банковских дней с даты счёта.",
    "Рецепт борща: свёкла, капуста, говядина.",
]


def main() -> int:
    body = json.dumps(
        {
            "model": "bge-reranker-v2-m3",
            "query": QUERY,
            "documents": DOCS,
            "top_n": 3,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print("fail: cannot reach", URL, exc)
        return 1
    results = data.get("results")
    if not results:
        print("fail: no results", data)
        return 1
    best = min(results, key=lambda r: -float(r.get("relevance_score", 0)))
    idx = int(best["index"])
    print("best_index", idx, "score", best.get("relevance_score"))
    print("text", DOCS[idx][:80])
    if idx != 1:
        print("fail: expected index 1 (contract clause)")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
