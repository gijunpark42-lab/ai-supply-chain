"""gpu_prices: Shadeform's hourly_price is in CENTS for the WHOLE instance, so $/GPU-hour = hourly_price / 100 / num_gpus.

Fixture: gpu_shadeform_instance_types_excerpt.json = four real offers from https://api.shadeform.ai/v1/instances/types
(fetched 2026-10-17), trimmed to the fields fetch_shadeform reads. The request itself is replaced by a stand-in.
"""
import json
import unittest
from unittest import mock

from market import gpu_prices
from tests.market.helpers import FIXED_TODAY, fixture_text


class FakeResponse:
    """The few parts of a requests.Response that fetch_shadeform uses."""

    def __init__(self, data, status_code=200):
        self.data, self.status_code = data, status_code

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def run_shadeform(data):
    with mock.patch.object(gpu_prices, "get", lambda *args, **kwargs: FakeResponse(data)), \
            mock.patch.object(gpu_prices, "today", lambda: FIXED_TODAY):
        return {r["gpu"]: r for r in gpu_prices.fetch_shadeform()}


class ShadeformPerGpuPrice(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(fixture_text("gpu_shadeform_instance_types_excerpt.json"))
        self.rows = run_shadeform(self.data)

    def test_cents_per_instance_become_dollars_per_gpu(self):
        h100 = self.rows["H100"]
        # hyperstack 8x H100 at 2080 cents = $2.60 per GPU; voltagepark 8x at 1592 = $1.99; latitude 1x at 199 = $1.99
        self.assertEqual(h100["max"], 2.6)
        self.assertEqual(h100["min"], 1.99)
        self.assertEqual(h100["median"], 1.99)
        self.assertEqual(h100["offers"], 3)
        self.assertEqual(h100["providers"], 3)

    def test_a100_name_is_normalised(self):
        a100 = self.rows["A100"]                                     # gpu_type "A100_80G" -> A100
        self.assertEqual(a100["median"], 2.3)                        # 1840 cents / 100 / 8 GPUs
        self.assertEqual(a100["raw_types"], ["A100_80G"])
        self.assertEqual(a100["date"], FIXED_TODAY)

    def test_spot_only_cpu_only_and_insane_offers_are_skipped(self):
        extra = [
            {"cloud": "x", "num_gpus": 8, "gpu_type": "H100", "hourly_price": 100,          # spot only
             "availability": [{"rental_type": "spot", "available": True}]},
            {"cloud": "y", "num_gpus": 0, "gpu_type": None, "hourly_price": 50,            # CPU-only instance
             "availability": [{"rental_type": "on_demand", "available": True}]},
            {"cloud": "z", "num_gpus": 1, "gpu_type": "H100", "hourly_price": 9_999_999,    # $99,999.99/h: a typo
             "availability": [{"rental_type": "on_demand", "available": True}]},
        ]
        rows = run_shadeform({"instance_types": self.data["instance_types"] + extra})
        self.assertEqual(rows["H100"]["offers"], 3)                  # the same three offers as without them
        self.assertEqual(sorted(rows), ["A100", "H100"])


class GpuNames(unittest.TestCase):
    def test_gpu_key(self):
        self.assertEqual(gpu_prices.gpu_key("NVIDIA HGX B300"), "b300")
        self.assertEqual(gpu_prices.gpu_key("GB300 NVL72"), "gb300")              # not b300
        self.assertEqual(gpu_prices.gpu_key("H100 NVL"), "h100nvl")               # not h100
        self.assertEqual(gpu_prices.gpu_key("A100_80G"), "a100")

    def test_parse_money(self):
        self.assertEqual(gpu_prices.parse_money("from $1.55"), 1.55)
        self.assertEqual(gpu_prices.parse_money("$4.50/GPU-hr"), 4.5)
        self.assertIsNone(gpu_prices.parse_money("Contact sales"))


if __name__ == "__main__":
    unittest.main()
