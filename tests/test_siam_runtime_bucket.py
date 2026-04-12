from __future__ import annotations

import unittest

from src.siam_core.runtime_bucket import in_rollout, stable_bucket


class SiamRuntimeBucketTests(unittest.TestCase):
    def test_same_key_same_bucket(self) -> None:
        bucket_a = stable_bucket("session-123")
        bucket_b = stable_bucket("session-123")
        self.assertEqual(bucket_a, bucket_b)
        self.assertGreaterEqual(bucket_a, 0)
        self.assertLessEqual(bucket_a, 99)

    def test_rollout_deterministic(self) -> None:
        first = in_rollout("session-123", 10)
        second = in_rollout("session-123", 10)
        self.assertEqual(first, second)

    def test_distribution_sanity(self) -> None:
        buckets = {stable_bucket(f"key-{index}") for index in range(300)}
        self.assertGreaterEqual(len(buckets), 70)
        self.assertLessEqual(max(buckets), 99)
        self.assertGreaterEqual(min(buckets), 0)


if __name__ == "__main__":
    unittest.main()
