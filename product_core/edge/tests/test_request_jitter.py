import unittest
from types import SimpleNamespace

from app.providers.base import jitter_delay
from app.providers.topcv import TopCVProvider


class RequestJitterTests(unittest.TestCase):
    def test_jitter_is_bounded_and_injectable(self):
        self.assertEqual(jitter_delay(1.0, 0.25, lambda low, high: low), 0.75)
        self.assertEqual(jitter_delay(1.0, 0.25, lambda low, high: high), 1.25)
        self.assertEqual(jitter_delay(0, 0.25), 0)
        self.assertEqual(jitter_delay(2.0, 0), 2.0)

    def test_invalid_values_are_clamped(self):
        self.assertEqual(jitter_delay(-2, 0.25), 0)
        self.assertAlmostEqual(
            jitter_delay(1.0, 2.0, lambda low, high: low), 0.2)

    def test_topcv_full_backup_uses_gentler_limits(self):
        provider = TopCVProvider(SimpleNamespace(), log=lambda _msg: None)
        provider.run_mode = "tatca"
        self.assertEqual(provider.concurrency_limit(), 2)
        self.assertEqual(provider.minimum_item_delay_ms(), 600)
        self.assertEqual(provider.minimum_page_delay_ms(), 800)
        self.assertEqual(provider._request_interval(), 0.25)

        provider.run_mode = "moi"
        self.assertEqual(provider.concurrency_limit(), 4)
        self.assertEqual(provider.minimum_item_delay_ms(), 250)
        self.assertEqual(provider.minimum_page_delay_ms(), 350)
        self.assertEqual(provider._request_interval(), 0.08)


if __name__ == "__main__":
    unittest.main()
