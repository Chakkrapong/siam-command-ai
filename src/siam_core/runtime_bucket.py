from __future__ import annotations

import hashlib


def stable_bucket(key: str) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value % 100


def in_rollout(key: str, percent: int) -> bool:
    bounded = max(0, min(100, int(percent)))
    if bounded <= 0:
        return False
    if bounded >= 100:
        return True
    return stable_bucket(key) < bounded
